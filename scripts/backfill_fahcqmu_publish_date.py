#!/usr/bin/env python3
"""
fahcqmu 1367 条 NULL publish_date 历史数据回填脚本 (一次性)
==============================================================

背景 (2026-06-26 11:30 lewellyn 报告):
  projects_fahcqmu 1667 条中, 1367 条 (82%) publish_date 为 NULL.
  涵盖所有 7 个分类 (cgglczb2_jggs 763 + cgglczb2_cggg 547 + dygg 33 + qt 16 + 其他 8).

根因 (3 重):
  1. 历史 parser 抓不到 (2026-06-25 23:09 首次批量入库时 list 页结构不同)
  2. Upsert 保护 (AGENTS.md 6-5 铁律): publish_date 在 timestamp_protected_cols
  3. Detail page 是 JS shell (1.2KB, 无 <span class="time">)

策略:
  启动 FahcqmuCrawler 跑 fetch_all_lists() 7 类全翻页 (~3min)
  内存建 {url → (publish_date, publish_date_raw, info_type, org_unit)} map
  UPDATE 条件: publish_date IS NULL AND url IN (...) AND new_publish_date IS NOT NULL
  
  不修改 upsert 保护逻辑 (6-5 铁律是设计正确的)
  不解析 JS shell 详情页 (SPA, 需 Playwright 重构, 独立 PR)

参数:
  --dry-run            只统计不写库
  --limit N            限制处理条数 (0 = 不限)
  --batch 100          每批 100 条处理后 commit 一次

用法:
  python3 scripts/backfill_fahcqmu_publish_date.py --dry-run          # 预览
  python3 scripts/backfill_fahcqmu_publish_date.py                    # 全量

预计:
  - 翻页: ~3min (7 类 × ~3 页 × 1s 限速)
  - UPDATE: <1min (1367 行)
  - 总耗时: ~3-5min
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, "/app")
os.environ.setdefault("DATABASE_URL", "postgresql://root:root123@postgres:5432/tender_scraper")

from app.crawlers.fahcqmu import FahcqmuCrawler
from app.database.db import Database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("backfill_fahcqmu_date")


def parse_date(raw: str) -> Optional[date]:
    """解析 list 页 <span class="time"> 里的 'YYYY.MM.DD' 格式."""
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


async def fetch_all_dates() -> Dict[str, Tuple[date, str]]:
    """跑 fetch_all_lists, 内存建 {url → (date, raw_str)} map.
    
    返回: dict[url, (publish_date, publish_date_raw)]
    """
    url_to_date: Dict[str, Tuple[date, str]] = {}
    
    async with FahcqmuCrawler() as crawler:
        log.info("📡 开始跑 fetch_all_lists() (7 类全翻页)...")
        start = time.time()
        all_items = await crawler.fetch_all_lists()
        elapsed = time.time() - start
        log.info(f"  ✓ fetch_all_lists 完成: {len(all_items)} 条, 用时 {elapsed:.1f}s")
        
        for item in all_items:
            if not item.url:
                continue
            pd = item.publish_date
            raw = item.publish_date_raw or ""
            if isinstance(pd, date) and not isinstance(pd, datetime):
                url_to_date[item.url] = (pd, raw)
            elif isinstance(pd, datetime):
                url_to_date[item.url] = (pd.date(), raw)
    
    return url_to_date


def select_null_date_urls(db: Database, limit: int = 0) -> List[Dict]:
    """SELECT publish_date IS NULL 的 url + title."""
    sql = """
        SELECT url, COALESCE(title, '') AS title
        FROM projects_fahcqmu
        WHERE publish_date IS NULL
        ORDER BY id ASC
    """
    if limit > 0:
        sql += f" LIMIT {int(limit)}"

    conn = db._get_conn()
    rows = conn.execute(sql).fetchall()
    # SQL 只 SELECT (url, title) 两列, 与结果集列对齐
    return [{"url": r[0], "title": r[1]} for r in rows]


def update_null_dates(db: Database, updates: List[Tuple[str, date, str]]) -> int:
    """批量 UPDATE NULL date.
    
    updates: list of (url, publish_date, publish_date_raw)
    返回: rowcount
    """
    if not updates:
        return 0
    
    conn = db._get_conn().conn
    cur = conn.cursor()
    cur.execute("""
        CREATE TEMP TABLE _backfill_updates (
            url TEXT PRIMARY KEY,
            new_publish_date DATE,
            new_publish_date_raw TEXT
        ) ON COMMIT DROP
    """)
    psycopg2_extras = __import__("psycopg2.extras", fromlist=["execute_values"])
    psycopg2_extras.execute_values(
        cur,
        "INSERT INTO _backfill_updates (url, new_publish_date, new_publish_date_raw) VALUES %s",
        updates,
        template="(%s, %s, %s)",
    )
    cur.execute("""
        UPDATE projects_fahcqmu t
        SET 
            publish_date = u.new_publish_date,
            publish_date_raw = u.new_publish_date_raw
        FROM _backfill_updates u
        WHERE t.url = u.url
          AND t.publish_date IS NULL
          AND u.new_publish_date IS NOT NULL
    """)
    rowcount = cur.rowcount
    conn.commit()
    return rowcount


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch", type=int, default=100)
    args = parser.parse_args()
    
    log.info("=" * 70)
    log.info(f"  fahcqmu NULL publish_date 回填脚本")
    log.info(f"  模式: {'DRY-RUN' if args.dry_run else 'WRITE'}, 限制: {args.limit or '全量'}, 批量: {args.batch}")
    log.info("=" * 70)
    
    db = Database()
    
    # 1. SELECT NULL date URLs
    log.info("📋 SELECT publish_date IS NULL 的 url...")
    targets = select_null_date_urls(db, limit=args.limit)
    log.info(f"  ✓ 找到 {len(targets)} 条")
    
    if not targets:
        log.info("🎉 无需回填")
        return
    
    # 2. 跑 fetch_all_lists 拿新日期
    url_to_date = asyncio.run(fetch_all_dates())
    log.info(f"  ✓ fetch_all_lists 拿到 {len(url_to_date)} 个 URL → 日期映射")
    
    # 3. 准备 updates
    updates: List[Tuple[str, date, str]] = []
    found = 0
    not_found = 0
    for t in targets:
        url = t["url"]
        if url in url_to_date:
            new_pd, new_raw = url_to_date[url]
            updates.append((url, new_pd, new_raw))
            found += 1
        else:
            not_found += 1
    
    log.info(f"\n📊 匹配结果:")
    log.info(f"  找到 (有日期): {found}")
    log.info(f"  未找到 (URL 已下架): {not_found}")
    log.info(f"  待 UPDATE: {len(updates)}")
    
    if args.dry_run:
        log.info("\n[DRY-RUN] 预览前 5 条:")
        for url, pd, raw in updates[:5]:
            log.info(f"  url: {url[:80]}")
            log.info(f"    new_publish_date: {pd}, raw: {raw!r}")
        log.info(f"\n[DRY-RUN] 不写库, 退出")
        return
    
    # 4. 实跑
    if not updates:
        log.info("🎉 无可写数据")
        return
    
    log.info(f"\n🚀 开始 UPDATE ({len(updates)} 条)...")
    start = time.time()
    updated = update_null_dates(db, updates)
    elapsed = time.time() - start
    log.info(f"  ✓ UPDATE 完成: {updated} 条, 用时 {elapsed:.1f}s")
    
    # 5. 验证
    cur = db._get_conn().conn.cursor()
    cur.execute("SELECT COUNT(*) FROM projects_fahcqmu WHERE publish_date IS NULL")
    remaining_null = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM projects_fahcqmu")
    total = cur.fetchone()[0]
    log.info(f"\n📊 验证:")
    log.info(f"  总数: {total}")
    log.info(f"  NULL date: {remaining_null} (期望显著下降)")


if __name__ == "__main__":
    main()