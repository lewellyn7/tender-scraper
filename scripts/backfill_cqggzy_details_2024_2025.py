#!/usr/bin/env python3
"""
cqggzy 2024-2025 历史数据详情补采脚本 (一次性)
================================================

背景 (2026-06-26 12:14 lewellyn 报告):
  projects_cqggzy 2024-2025 范围 86,181 条中, 9,862 条 (11%) 同时缺 fc + cp.
  这些行 publish_date 正常, 但 detail 阶段从未访问 (爬虫只跑每日增量, 历史数据缺失).
  缺 cp → Data 页列表卡片显示空白摘要.

策略:
  复用现有 CQGGZYCrawlerV2.fetch_details_parallel (并发 5, 限速 self.delay)
  单独 SELECT 9862 个 URL → 详情采集 → upsert_projects_cqggzy 批量写入
  upsert 已带 COALESCE 保护 (db.py:351-358), 已有 cp/fc 不被空值覆盖 (安全性)
  
  然后 (可选) 从新采集的 fc 截取 300 字生成 cp (跟 A 方案一样)

参数:
  --concurrency 5    并发数 (同 fetch_details_parallel 默认)
  --delay 0.2        每条间隔秒 (200ms, 防 IP 封禁)
  --batch 100        每批 100 条处理后短暂休息
  --retry 3          失败重试次数
  --limit 0          限制条数 (0 = 不限)
  --dry-run          只打印不写库
  --skip-cp          跳过 cp 自动生成 (只补 fc)

用法:
  python scripts/backfill_cqggzy_details_2024_2025.py --dry-run --limit 5   # 预览
  python scripts/backfill_cqggzy_details_2024_2025.py --limit 50            # 试水 50 条
  python scripts/backfill_cqggzy_details_2024_2025.py                      # 全量 (~30min)

预计:
  9862 条 × 200ms / 5 并发 ≈ 6.5 min 单程 + 重试 3x + 间歇 ≈ 30min 总耗时
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from typing import List, Dict

sys.path.insert(0, "/app")
os.environ.setdefault("DATABASE_URL", "postgresql://root:root123@postgres:5432/tender_scraper")

from app.crawlers.cqggzy_curl import CqggzyCurlCrawler
from app.database.db import Database
from app.models.tender import TenderInfo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("backfill_cqggzy_2024_2025")

# ━━━ 配置 ━━━
DATE_START = "2024-01-01"
DATE_END = "2025-12-31"
CP_MAX_LEN = 300
TABLE = "projects_cqggzy"


def make_cp(full_content: str) -> str:
    """从 full_content 生成 content_preview (前 300 字 + 智能断句)."""
    if not full_content:
        return ""
    text = " ".join(full_content.split())
    if len(text) <= CP_MAX_LEN:
        return text
    truncated = text[:CP_MAX_LEN]
    for sep in ["。", ".", "!", "?", "！", "？", ";", "；", "\n"]:
        idx = truncated.rfind(sep)
        if idx > CP_MAX_LEN * 0.7:
            return truncated[: idx + 1].strip()
    return truncated.strip()


def select_urls_without_detail(db: Database, limit: int = 0) -> List[Dict]:
    """SELECT 2024-2025 范围内 url + title, 过滤 fc+cp 都为空的行.

    返回: list of {id, url, title}
    """
    sql = f"""
        SELECT id, url, COALESCE(title, '') AS title
        FROM {TABLE}
        WHERE publish_date BETWEEN %s AND %s
          AND (content_preview IS NULL OR content_preview = '')
          AND (full_content    IS NULL OR full_content    = '')
        ORDER BY id ASC
    """
    params = [DATE_START, DATE_END]
    if limit > 0:
        sql += " LIMIT %s"
        params.append(int(limit))

    conn = db._get_conn()
    rows = conn.execute(sql, params).fetchall()
    cols = [d[0] for d in conn.execute(f"SELECT * FROM {TABLE} LIMIT 0").description]
    return [dict(zip(cols, r)) for r in rows]


def regenerate_cp_from_fc(db: Database) -> int:
    """对所有有 fc 但缺 cp 的行重新生成 cp (UPDATE).

    Backfill 完成后再调一次, 覆盖 cp 截取逻辑的回归.
    """
    sql = f"""
        UPDATE {TABLE}
        SET content_preview = SUBSTRING(REGEXP_REPLACE(full_content, '\\s+', ' ', 'g') FROM 1 FOR {CP_MAX_LEN})
        WHERE publish_date BETWEEN %s AND %s
          AND (content_preview IS NULL OR content_preview = '')
          AND full_content IS NOT NULL AND full_content != ''
    """
    conn = db._get_conn()
    raw_conn = conn.conn if hasattr(conn, 'conn') else conn
    cur = raw_conn.cursor()
    cur.execute(sql, [DATE_START, DATE_END])
    rowcount = cur.rowcount
    raw_conn.commit()
    return rowcount


async def backfill(
    concurrency: int = 5,
    delay: float = 0.2,
    batch: int = 100,
    retry: int = 3,
    limit: int = 0,
    dry_run: bool = False,
    skip_cp: bool = False,
):
    """主流程: SELECT 9862 URLs → 并发详情采集 → upsert."""
    db = Database()
    
    log.info("=" * 70)
    log.info(f"  cqggzy {DATE_START} ~ {DATE_END} 详情补采")
    log.info(f"  并发: {concurrency}, 延迟: {delay}s, 批量: {batch}, 重试: {retry}")
    log.info(f"  限制: {limit or '全量'}, 模式: {'DRY-RUN' if dry_run else 'WRITE'}")
    log.info("=" * 70)
    
    # 1. SELECT 待补 URL
    log.info("📋 SELECT 待补 URL...")
    targets = select_urls_without_detail(db, limit=limit)
    log.info(f"  ✓ 找到 {len(targets)} 条")
    
    if not targets:
        log.info("🎉 无需补采")
        return
    
    # 2. 预览前 5 条
    if dry_run or limit <= 5:
        log.info("\n📄 预览前 5 条:")
        for t in targets[:5]:
            log.info(f"  id={t['id']} url={t['url'][:80]}")
            log.info(f"    title: {t['title'][:60]}")
    
    if dry_run:
        log.info("\n[DRY-RUN] 不采集, 退出")
        return
    
    # 3. 构建 TenderInfo (详情采集器需要的格式)
    tenders = []
    for t in targets:
        tender = TenderInfo(url=t["url"], title=t.get("title", ""))
        tender.publish_date = None  # 让采集器重新填
        tenders.append(tender)
    
    # 4. 启动爬虫并发采集
    log.info(f"\n🚀 开始采集详情 (并发 {concurrency})...")
    start_time = time.time()
    success_count = 0
    failed_count = 0
    failed_urls = []
    
    async with CqggzyCurlCrawler(browser=None) as crawler:
        # 分批, 每批后短暂休息
        for i in range(0, len(tenders), batch):
            batch_tenders = tenders[i : i + batch]
            log.info(f"\n  Batch {i // batch + 1}/{(len(tenders) + batch - 1) // batch} "
                     f"({len(batch_tenders)} 条, 累计成功 {success_count}, 失败 {failed_count})")
            
            try:
                results = await crawler.fetch_details_parallel(batch_tenders, max_retries=retry)
                
                # 5. 过滤成功的, 批量 upsert
                success_tenders = [t for t in results if t.full_content]
                if success_tenders:
                    # 用 db.tender_to_db_row 转换格式
                    rows = []
                    for t in success_tenders:
                        row = db.tender_to_db_row(t)
                        rows.append(row)
                    
                    if rows:
                        db.upsert_projects(rows)
                        success_count += len(success_tenders)
                        log.info(f"    ✓ upsert 成功 {len(success_tenders)} 条")
                
                # 统计失败
                for t in results:
                    if not t.full_content:
                        failed_count += 1
                        if len(failed_urls) < 10:
                            failed_urls.append(t.url)
                            
            except Exception as e:
                log.error(f"    ❌ Batch 失败: {e}")
                failed_count += len(batch_tenders)
            
            # 间歇
            if i + batch < len(tenders):
                await asyncio.sleep(1.0)
    
    elapsed = time.time() - start_time
    rate = success_count / elapsed if elapsed > 0 else 0
    
    log.info("\n" + "=" * 70)
    log.info(f"  ✓ 完成: 成功 {success_count}, 失败 {failed_count}, 用时 {elapsed:.1f}s ({rate:.1f}/s)")
    if failed_urls:
        log.info(f"  ❌ 失败 URL (前 10):")
        for u in failed_urls:
            log.info(f"    {u}")
    log.info("=" * 70)
    
    # 6. cp 自动生成 (从新采集的 fc)
    if not skip_cp and success_count > 0:
        log.info("\n🔄 从新采集的 fc 自动生成 cp...")
        regenerated = regenerate_cp_from_fc(db)
        log.info(f"  ✓ 更新 cp: {regenerated} 条")
    
    # 7. 验证最终状态
    conn = db._get_conn()
    result = conn.execute(f"""
        SELECT 
            COUNT(*) FILTER (WHERE (content_preview IS NULL OR content_preview = '')) as need_cp,
            COUNT(*) FILTER (WHERE (full_content IS NULL OR full_content = '')) as need_fc
        FROM {TABLE}
        WHERE publish_date BETWEEN %s AND %s
    """, [DATE_START, DATE_END]).fetchone()
    
    log.info(f"\n📊 {DATE_START} ~ {DATE_END} 现状:")
    log.info(f"  缺 cp: {result[0]} 条 (期望显著下降)")
    log.info(f"  缺 fc: {result[1]} 条 (期望显著下降)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--batch", type=int, default=100)
    parser.add_argument("--retry", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0, help="限制条数 (0=全量)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-cp", action="store_true", help="跳过 cp 自动生成")
    args = parser.parse_args()
    
    asyncio.run(backfill(
        concurrency=args.concurrency,
        delay=args.delay,
        batch=args.batch,
        retry=args.retry,
        limit=args.limit,
        dry_run=args.dry_run,
        skip_cp=args.skip_cp,
    ))


if __name__ == "__main__":
    main()