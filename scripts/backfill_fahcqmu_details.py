#!/usr/bin/env python3
"""
fahcqmu 历史数据详情补采脚本 (一次性)
==========================================

背景 (2026-06-26 09:52 lewellyn 报告):
  1667 条 fahcqmu 项目中, 1367 条 (82%) full_content + content_preview 都为空.
  仅有 300 条 (18%) 在详情阶段采集时填充.

原因:
  首轮采集 (PR #42) 时, list + detail 阶段总耗时 ~16min, detail_limit=300 覆盖 18% 数据;
  剩余 82% 历史数据从未被详情采集器访问过.

策略:
  复用现有 FahcqmuCrawler.fetch_details_parallel (并发 5, 限速 self.delay)
  单独 SELECT 1367 个 URL → 详情采集 → upsert_projects_fahcqmu 批量写入
  upsert 已带 COALESCE 保护 (db.py:491), 已有 cp/fc 不被空值覆盖 (安全性)

参数:
  --batch 100        每批 100 条处理后短暂休息 (避免长连接)
  --concurrency 5    并发数 (同 fetch_details_parallel 默认值)
  --delay 0.2        每条间隔秒 (默认 0.2 = 200ms, 防 IP 封禁)
  --retry 3          失败重试次数
  --skip-existing    跳过已有 cp/fc 的行 (默认 True)
  --limit 0          限制条数 (0 = 不限, 仅用于测试)
  --dry-run          只打印不写库

用法:
  python scripts/backfill_fahcqmu_details.py --dry-run         # 预览
  python scripts/backfill_fahcqmu_details.py --limit 5         # 跑 5 条试水
  python scripts/backfill_fahcqmu_details.py                   # 全量 (预计 ~11min)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime
from typing import List, Dict

# 容器内运行: 把 /app 加入路径 (与 backfill_6-2.py 一致)
sys.path.insert(0, "/app")
os.environ.setdefault("DATABASE_URL", "postgresql://root:root123@postgres:5432/tender_scraper")

from app.crawlers.fahcqmu import (
    FahcqmuCrawler,
    tender_to_db_row,
    collect_org_unit,
)
from app.database.db import Database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("backfill_fahcqmu")


def select_urls_without_detail(db: Database, limit: int = 0) -> List[Dict]:
    """SELECT 全表 url + org_unit, 过滤 cp/fc 都为空的行.

    返回: list of {url, org_unit, has_existing_cp, has_existing_fc}
    """
    sql = """
        SELECT url,
               COALESCE(org_unit, '') AS org_unit,
               (content_preview IS NOT NULL AND content_preview <> '') AS has_cp,
               (full_content    IS NOT NULL AND full_content    <> '') AS has_fc
        FROM projects_fahcqmu
        WHERE (content_preview IS NULL OR content_preview = '')
          AND (full_content    IS NULL OR full_content    = '')
        ORDER BY id ASC
    """
    if limit > 0:
        sql += f" LIMIT {int(limit)}"

    conn = db._get_conn().conn
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return [
        {"url": r[0], "org_unit": r[1], "has_existing_cp": r[2], "has_existing_fc": r[3]}
        for r in rows
    ]


async def fetch_one_with_retry(
    crawler: FahcqmuCrawler,
    url: str,
    retry: int,
) -> tuple[bool, str]:
    """采集单个详情 + 失败重试. 返回 (success, error_msg)."""
    from app.models.tender import TenderInfo
    item = TenderInfo(url=url, title="")
    last_err = ""
    for attempt in range(1, retry + 1):
        try:
            detailed = await crawler.fetch_detail(item)
            if detailed.full_content and len(detailed.full_content) > 50:
                return True, ""
            last_err = f"empty fc after parse (len={len(detailed.full_content)})"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        if attempt < retry:
            await asyncio.sleep(2 ** attempt * 0.5)  # 0.5s, 1s, 2s
    return False, last_err


async def run(args: argparse.Namespace):
    db = Database()
    crawler = FahcqmuCrawler()

    # 1. SELECT 待补采的 URL
    log.info(f"=== SELECT 待补采 URL (limit={args.limit}, skip_existing={args.skip_existing}) ===")
    pending = select_urls_without_detail(db, limit=args.limit)
    if args.skip_existing:
        # 保险: 即使 URL 没 cp/fc, 也跳过 has_existing_* 为 True 的 (理论上不会发生)
        pending = [p for p in pending if not (p["has_existing_cp"] or p["has_existing_fc"])]
    log.info(f"待补采: {len(pending)} 条")

    if not pending:
        log.info("无待补采数据, 退出")
        return

    if args.dry_run:
        log.info(f"[DRY-RUN] 前 5 条预览:")
        for p in pending[:5]:
            log.info(f"  - {p['url']} ({p['org_unit']})")
        log.info(f"[DRY-RUN] 全部 {len(pending)} 条 URL 已列出, 不采集不写入")
        return

    # 2. 启动 crawler (aiohttp session)
    await crawler.__aenter__()

    # 3. 分批采集 + 写入
    stats = {"ok": 0, "fail": 0, "skipped": 0, "total": len(pending)}
    batch_size = args.batch
    started_at = time.time()

    try:
        for i in range(0, len(pending), batch_size):
            batch = pending[i : i + batch_size]
            batch_idx = i // batch_size + 1
            total_batches = (len(pending) + batch_size - 1) // batch_size
            log.info(f"=== 批次 {batch_idx}/{total_batches}: {len(batch)} 条 ===")

            # 并发采集 (semaphore by crawler)
            sem = asyncio.Semaphore(args.concurrency)

            async def _process(p: Dict) -> Dict:
                async with sem:
                    ok, err = await fetch_one_with_retry(crawler, p["url"], args.retry)
                    if not ok:
                        return {"ok": False, "url": p["url"], "err": err, "item": None}
                    # 重新跑详情拿到 TenderInfo 完整对象 (cp/fc 都在 fetch_detail 返回里)
                    # 但 fetch_one_with_retry 内部 item 是空的, 重新跑一遍
                    from app.models.tender import TenderInfo
                    item = TenderInfo(url=p["url"], title="")
                    detailed = await crawler.fetch_detail(item)
                    return {
                        "ok": True,
                        "url": p["url"],
                        "err": "",
                        "item": detailed,
                        "org_unit": p["org_unit"],
                    }

            results = await asyncio.gather(*[_process(p) for p in batch], return_exceptions=True)

            # 4. 批量写库
            rows_to_write = []
            for r in results:
                if isinstance(r, Exception):
                    log.warning(f"异常: {r}")
                    stats["fail"] += 1
                    continue
                if not r["ok"]:
                    log.warning(f"  失败: {r['url']} - {r['err']}")
                    stats["fail"] += 1
                    continue
                row = tender_to_db_row(r["item"], org_unit=r["org_unit"])
                row["scraped_at"] = datetime.now()
                rows_to_write.append(row)
                stats["ok"] += 1

            if rows_to_write:
                try:
                    db.upsert_projects_fahcqmu(rows_to_write)
                    log.info(f"  ✓ 写入 {len(rows_to_write)} 条")
                except Exception as e:
                    log.error(f"  ✗ 批量写入失败: {e}")
                    stats["fail"] += len(rows_to_write)
                    stats["ok"] -= len(rows_to_write)

            # 进度
            elapsed = time.time() - started_at
            speed = stats["ok"] / elapsed if elapsed > 0 else 0
            remaining = (stats["total"] - stats["ok"] - stats["fail"]) / speed if speed > 0 else 0
            log.info(
                f"  进度: {stats['ok']}/{stats['total']} ok, "
                f"{stats['fail']} fail, "
                f"{speed:.1f}条/s, "
                f"预计剩余 {remaining:.0f}s"
            )

            # 批次间休息 (避免长连接 + IP 封禁)
            if i + batch_size < len(pending):
                await asyncio.sleep(args.delay * 10)
    finally:
        await crawler.__aexit__(None, None, None)

    # 5. 总结
    elapsed = time.time() - started_at
    log.info(f"=== 完成 ===")
    log.info(f"  成功: {stats['ok']}")
    log.info(f"  失败: {stats['fail']}")
    log.info(f"  跳过: {stats['skipped']}")
    log.info(f"  耗时: {elapsed:.0f}s ({elapsed/60:.1f}min)")
    log.info(f"  平均速度: {stats['ok']/elapsed if elapsed > 0 else 0:.2f}条/s")


def main():
    p = argparse.ArgumentParser(description="fahcqmu 历史详情补采")
    p.add_argument("--batch", type=int, default=100, help="每批条数")
    p.add_argument("--concurrency", type=int, default=5, help="并发数")
    p.add_argument("--delay", type=float, default=0.2, help="每条间隔秒")
    p.add_argument("--retry", type=int, default=3, help="重试次数")
    p.add_argument("--limit", type=int, default=0, help="限制条数 (0=全部)")
    p.add_argument("--skip-existing", action="store_true", default=True, help="跳过已有 cp/fc 的行")
    p.add_argument("--dry-run", action="store_true", help="只预览不执行")
    args = p.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()