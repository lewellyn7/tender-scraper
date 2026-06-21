#!/usr/bin/env python3
"""增量向量回填脚本 v2 (2026-06-20)

背景:
- vector_store 覆盖率仅 10.4% (11.3K / 109K)
- 6-5 后 14 天未回填, AI 召回实际走 TF-IDF fallback
- 现有 reindex_vector_store.py 是全量 (TRUNCATE 后重建), 不能增量

设计:
- 增量查询: projects_cqggzy.id > checkpoint 且不在 vector_store 中
- Checkpoint: data/checkpoints/backfill_vectors.json
- 速率限制: batch=50, 失败重试 3 次 (指数退避)
- 进度日志: 每 100 条打 log, 含 ETA
- dry-run: 仅打印统计不入库

变更 (2026-06-20):
- doc_id 从 `tender_{pg_id}` 改为 `tender_{url_hash[:16]}` (与 vectorize.py 一致)
- 原因: vectorize 在 PG upsert 前运行, 不能依赖 pg_id
- 用 url_hash 完全解耦, 两路入口产出相同 doc_id
- 现有 109K vector 需重建 (TRUNCATE 后跑本脚本, ~33min)

用法:
  P=$(grep '^DB_PASSWORD=' .env | cut -d= -f2)
  docker exec -e "DBURL=postgresql://root:${P}@postgres:5432/tender_scraper" \\
    tender-scraper-web python3 /app/scripts/backfill_vectors_incremental.py \\
    [--batch 50] [--limit 1000] [--dry-run] [--resume-from N]

预期耗时 (vLLM 4B + 2560 维 + 6 qps):
- 1,000 条: 3-5 min
- 10,000 条: 30-50 min
- 98,000 条 (全覆盖): 5-7 hours
"""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import psycopg2

sys.path.insert(0, "/app")

from loguru import logger

from app.services.vector_store import get_vector_store

CHECKPOINT_DIR = Path(os.getenv("CHECKPOINT_DIR", "/tmp/backfill_checkpoints"))
CHECKPOINT_FILE = CHECKPOINT_DIR / "backfill_vectors.json"


def load_checkpoint() -> int:
    """读取上次处理到的 project_id, 用于断点续传"""
    if not CHECKPOINT_FILE.exists():
        return 0
    try:
        data = json.loads(CHECKPOINT_FILE.read_text())
        return int(data.get("last_project_id", 0))
    except Exception as e:
        logger.warning(f"Checkpoint 读取失败, 从 0 开始: {e}")
        return 0


def save_checkpoint(last_id: int, total_processed: int, duration_s: float) -> None:
    """保存 checkpoint (原子写入, 防止中断时损坏)"""
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "last_project_id": last_id,
        "total_processed": total_processed,
        "last_run_at": time.time(),
        "last_run_duration_s": duration_s,
    }
    # 写到临时文件, 原子 rename
    tmp = CHECKPOINT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.rename(CHECKPOINT_FILE)


def fetch_pending_projects(conn, after_id: int, limit: int) -> list:
    """查询待向量化的项目 (id > after_id 且不在 vector_store 中)

    排除规则:
    - title 为空 (无法构造有意义的 embedding)
    - 已存在 vector_store.doc_id (doc_id = url_hash[:16])
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT p.id, p.url, p.title, p.content_preview, p.full_content,
               p.publish_date, p.info_type, p.business_type
        FROM projects_cqggzy p
        WHERE p.id > %s
          AND (p.title IS NOT NULL AND p.title != '')
          AND NOT EXISTS (
              SELECT 1 FROM vector_store v
              WHERE v.doc_id = 'tender_' || substring(encode(sha256(p.url::bytea), 'hex'), 1, 16)
          )
        ORDER BY p.id ASC
        LIMIT %s
        """,
        (after_id, limit),
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_total_remaining(conn, after_id: int) -> int:
    """统计总剩余数 (用于 ETA 估算)"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) FROM projects_cqggzy p
        WHERE p.id > %s
          AND (p.title IS NOT NULL AND p.title != '')
          AND NOT EXISTS (
              SELECT 1 FROM vector_store v
              WHERE v.doc_id = 'tender_' || substring(encode(sha256(p.url::bytea), 'hex'), 1, 16)
          )
        """,
        (after_id,),
    )
    return cur.fetchone()[0]


def build_doc(project: dict) -> dict:
    """构造 vector doc (复用 reindex 格式, doc_id 用 url_hash[:16])"""
    title = project.get("title") or ""
    preview = (project.get("content_preview") or "")[:500]
    full = (project.get("full_content") or "")[:500]
    text = f"{title}\n{preview}\n{full}".strip()[:1000]

    url = project.get("url") or ""
    if url:
        doc_id = f"tender_{hashlib.sha256(url.encode()).hexdigest()[:16]}"
    else:
        doc_id = f"tender_nourl_{hashlib.sha256((title or '').encode()).hexdigest()[:16]}"

    return {
        "id": doc_id,
        "text": text or title,
        "metadata": {
            "url": url,
            "title": title[:200],
            "publish_date": str(project.get("publish_date") or ""),
            "info_type": project.get("info_type") or "",
            "business_type": project.get("business_type") or "",
            "source": "cqggzy",
            "project_id": project["id"],
        },
    }


def backfill_batch(vs, batch: list, max_retries: int = 3) -> int:
    """批量回填, 带重试. 返回成功数"""
    if not batch:
        return 0
    docs = [build_doc(p) for p in batch]
    for attempt in range(max_retries):
        try:
            result = vs.upsert_documents(docs)
            return result.get("inserted", len(docs))
        except Exception as e:
            wait_s = 2 ** attempt
            logger.warning(
                f"  ⚠️  批次失败 (attempt {attempt+1}/{max_retries}): {e}, "
                f"等待 {wait_s}s 重试"
            )
            time.sleep(wait_s)
    logger.error(f"  ❌ 批次最终失败, 跳过 {len(batch)} 条: {[p['id'] for p in batch[:5]]}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="增量向量回填 v2")
    ap.add_argument("--batch", type=int, default=50, help="每批条数 (默认 50)")
    ap.add_argument("--limit", type=int, default=None, help="最多处理多少条 (默认全部)")
    ap.add_argument("--resume-from", type=int, default=None,
                    help="从指定 project_id 之后开始 (覆盖 checkpoint)")
    ap.add_argument("--dry-run", action="store_true", help="仅统计不写入")
    ap.add_argument("--max-batches", type=int, default=None,
                    help="最多跑多少批 (测试用, 默认无限)")
    args = ap.parse_args()

    dburl = os.environ.get("DBURL")
    if not dburl:
        print("❌ DBURL env var required")
        sys.exit(1)

    # 1. 决定起始 ID
    if args.resume_from is not None:
        after_id = args.resume_from
        logger.info(f"⏭️  使用 --resume-from={after_id} (覆盖 checkpoint)")
    else:
        after_id = load_checkpoint()
        logger.info(f"📍 从 checkpoint 恢复: after_id={after_id}")

    conn = psycopg2.connect(dburl)
    vs = get_vector_store()

    # 2. 总数统计
    total_remaining = get_total_remaining(conn, after_id)
    logger.info(f"📊 待处理: {total_remaining:,} 条 (after_id={after_id})")

    if total_remaining == 0:
        logger.info("✅ 无待处理项目, 退出")
        return

    if args.dry_run:
        logger.info(f"🔍 DRY RUN: 本次会处理 {args.limit or total_remaining:,} 条")
        # 抽 3 条示例
        sample = fetch_pending_projects(conn, after_id, 3)
        for s in sample:
            doc = build_doc(s)
            logger.info(f"  示例 id={doc['id']}, text_len={len(doc['text'])}, "
                        f"url={doc['metadata']['url'][:60]}")
        return

    # 3. 批量循环
    total_processed = 0
    total_failed = 0
    t_start = time.time()
    batch_count = 0
    last_id = after_id

    while True:
        # 拉一批
        batch = fetch_pending_projects(conn, after_id=last_id, limit=args.batch)
        if not batch:
            break

        inserted = backfill_batch(vs, batch)
        total_processed += inserted
        total_failed += len(batch) - inserted
        last_id = max(p["id"] for p in batch)
        batch_count += 1

        # 进度日志
        elapsed = time.time() - t_start
        rate = total_processed / elapsed if elapsed > 0 else 0
        eta = (total_remaining - total_processed) / rate if rate > 0 else 0
        logger.info(
            f"  [{total_processed:>5}/{total_remaining:,}]  "
            f"last_id={last_id}  "
            f"elapsed={elapsed:.0f}s  "
            f"rate={rate:.1f}/s  "
            f"ETA={eta/60:.1f}min  "
            f"failed={total_failed}"
        )

        # 写 checkpoint (每批)
        save_checkpoint(last_id, total_processed, elapsed)

        # 退出条件
        if args.max_batches and batch_count >= args.max_batches:
            logger.info(f"⏸️  达到 --max-batches={args.max_batches}, 暂停")
            break
        if args.limit and total_processed >= args.limit:
            logger.info(f"⏸️  达到 --limit={args.limit}, 暂停")
            break

    # 4. 汇总
    elapsed = time.time() - t_start
    final_size = vs.stats()["total_vectors"]
    logger.success(
        f"🎉 完成: inserted={total_processed} failed={total_failed} "
        f"elapsed={elapsed:.0f}s ({elapsed/60:.1f}min) "
        f"rate={total_processed/elapsed:.1f}/s"
    )
    logger.info(f"📊 新向量库 size: {final_size:,}")


if __name__ == "__main__":
    main()
