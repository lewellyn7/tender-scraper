#!/usr/bin/env python3
"""全量向量入库脚本 — 将 favorites 历史数据批量向量化写入向量库

用法:
    python scripts/backfill_vectors.py [--batch 50] [--dry-run]

将 favorites 表中所有项目的 title + content_preview 拼接为文本，
通过 vLLM Qwen3-Embedding-4B 向量化后写入 ChromaDB。

预期耗时（估算）:
    1000 条 × 50 字/条 → ~3-5 分钟（受 vLLM QPS 限制）
"""
import argparse
import asyncio
import hashlib
import sys
import os
from concurrent.futures import ThreadPoolExecutor

# ── 项目路径 setup ────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

logger.add("logs/backfill_vectors.log", rotation="100MB", retention="7days", level="INFO")


def _text_for_vector(p: dict) -> str:
    """构造向量化用的文本片段"""
    parts = []
    title = p.get("title", "")
    if title:
        parts.append(f"标题: {title}")
    budget = p.get("budget", "")
    if budget:
        parts.append(f"预算: {budget}")
    region = p.get("region", "")
    if region:
        parts.append(f"地区: {region}")
    tender_type = p.get("tender_type", "")
    if tender_type:
        parts.append(f"类型: {tender_type}")
    content = (p.get("content_preview") or "")[:500]
    if content:
        parts.append(f"摘要: {content}")
    return " | ".join(parts) if parts else title


def _make_id(p: dict) -> str:
    """生成稳定 ID"""
    url = p.get("project_url", "") or p.get("url", "")
    key = f"{url}:{p.get('title', '')}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _load_favorites() -> list:
    """从 favorites 表读取所有记录"""
    from app.database import get_db
    db = get_db()
    conn = db._get_conn()
    rows = conn.execute(
        "SELECT project_url, title, url, budget, region, tender_type, "
        "publish_date, deadline, content_preview, source_url, keywords_matched "
        "FROM favorites LIMIT 5000"
    ).fetchall()
    return [dict(r) for r in rows]


async def _encode_batch(texts: list) -> list:
    """通过 vLLM 批量向量化"""
    from app.services.vector_store import encode_texts
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, encode_texts, texts)


async def backfill(batch_size: int = 50, dry_run: bool = False):
    """全量向量入库主流程"""
    logger.info(f"[backfill] 启动，batch_size={batch_size}, dry_run={dry_run}")

    # 1. 读取数据
    favorites = _load_favorites()
    logger.info(f"[backfill] 读取到 {len(favorites)} 条 favorites")
    if not favorites:
        logger.warning("[backfill] favorites 表为空，无需入库")
        return

    # 2. 构建文本
    texts = [_text_for_vector(p) for p in favorites]
    ids = [_make_id(p) for p in favorites]
    payloads = [
        {
            "title": p.get("title", ""),
            "url": p.get("project_url", "") or p.get("url", ""),
            "budget": p.get("budget", ""),
            "region": p.get("region", ""),
            "tender_type": p.get("tender_type", ""),
            "publish_date": p.get("publish_date", ""),
            "deadline": p.get("deadline", ""),
            "source": p.get("source_url", ""),
            "keywords": p.get("keywords_matched", ""),
        }
        for p in favorites
    ]

    if dry_run:
        logger.info(f"[backfill] DRY RUN: 本应入库 {len(ids)} 条")
        for i, (tid, t) in enumerate(zip(ids[:3], texts[:3])):
            logger.info(f"[backfill] 示例 #{i+1}: id={tid}, text={t[:80]}...")
        return

    # 3. 批量向量化 + 入库
    from app.services.vector_store import get_vector_store
    vs = get_vector_store()

    total = len(texts)
    inserted = 0
    errors = 0

    for i in range(0, total, batch_size):
        batch_ids = ids[i:i + batch_size]
        batch_texts = texts[i:i + batch_size]
        batch_payloads = payloads[i:i + batch_size]

        try:
            embs = await _encode_batch(batch_texts)
            vs.upsert(batch_ids, embs, batch_payloads)
            inserted += len(batch_ids)
            logger.info(f"[backfill] 进度 {inserted}/{total}")
        except Exception as e:
            logger.error(f"[backfill] 批次 {i}-{i+batch_size} 失败: {e}")
            errors += len(batch_ids)

    logger.info(f"[backfill] 完成: 成功 {inserted}/{total}，失败 {errors}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="全量向量入库")
    parser.add_argument("--batch", type=int, default=50, help="每批处理条数")
    parser.add_argument("--dry-run", action="store_true", help="仅打印不写入")
    args = parser.parse_args()

    asyncio.run(backfill(batch_size=args.batch, dry_run=args.dry_run))
