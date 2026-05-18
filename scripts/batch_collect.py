#!/usr/bin/env python3
"""历史数据回填脚本 - 采集 1-4 月数据并存入数据库
用法: python scripts/batch_collect.py --start 2026-01-01 --end 2026-04-30
"""
import argparse
import asyncio
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger
from app.core.browser import StealthBrowser
from app.crawlers.cqggzy import CQGGZYCrawlerV2
from app.crawlers.ccgp import CCGPCrawlerV3
from app.database import get_db
from config.settings import settings

logger.add(sys.stderr, format="{time:HH:mm:ss} | {level: <8} | {message}", level="INFO", colorize=False)


def tender_to_row(tender) -> dict:
    """将 TenderInfo 转换为 DB 行 dict（用于 upsert）"""
    return {
        "url": tender.url or "",
        "title": tender.title or "",
        "category": getattr(tender, 'category', "") or "",
        "info_type": getattr(tender, 'info_type', "") or "",
        "business_type": getattr(tender, 'business_type', "") or "",
        "publish_date": tender.publish_date,
        "publish_date_raw": getattr(tender, 'publish_date_raw', "") or "",
        "content_preview": (tender.content_preview or "").replace("\n", " ")[:500],
        "full_content": tender.full_content or "",
        "budget": getattr(tender, 'budget', "") or "",
        "bid_amount": getattr(tender, 'bid_amount', "") or "",
        "deadline": getattr(tender, 'deadline', "") or "",
        "region": getattr(tender, 'region', "") or "",
        "industry": getattr(tender, 'industry', "") or "",
        "tender_type": getattr(tender, 'tender_type', "") or "",
        "project_overview": getattr(tender, 'project_overview', "") or "",
        "bidder_requirements": getattr(tender, 'bidder_requirements', "") or "",
        "submission_deadline": getattr(tender, 'submission_deadline', "") or "",
        "contact_name": getattr(tender, 'contact_name', "") or "",
        "contact_phone": getattr(tender, 'contact_phone', "") or "",
        "contact_email": getattr(tender, 'contact_email', "") or "",
        "attachments_count": getattr(tender, 'attachments_count', 0) or 0,
        "attachments": getattr(tender, 'attachments', '[]') or "[]",
        "keywords_matched": ",".join(tender.keywords_matched) if tender.keywords_matched else "",
        "source_url": getattr(tender, 'source_url', "") or "",
        "scraped_at": datetime.now(),
        "scraped_by": getattr(tender, 'version', "") or "",
    }


async def collect_month(db, cqggzy, ccgp, year: int, month: int, max_pages: int = 20):
    """采集某月的数据（所有页），结果写入数据库"""
    start_dt = datetime(year, month, 1)
    if month == 12:
        end_dt = datetime(year + 1, 1, 1)
    else:
        end_dt = datetime(year, month + 1, 1)

    all_tenders = []

    logger.info(f"📅 {year}-{month:02d} 开始采集...")

    # 并行采集：政府采购 + 工程招投标 + CCGP 三类
    gov_task = cqggzy.fetch_lists_parallel(
        category="gov_purchase", pages=list(range(1, max_pages + 1)),
        start_date=start_dt, end_date=end_dt
    )
    eng_task = cqggzy.fetch_lists_parallel(
        category="engineering", pages=list(range(1, max_pages + 1)),
        start_date=start_dt, end_date=end_dt
    )
    ccgp_tasks = [
        ccgp.fetch_list(info_type="采购意向", page_num=1, start_date=start_dt, end_date=end_dt),
        ccgp.fetch_list(info_type="采购公告", page_num=1, start_date=start_dt, end_date=end_dt),
        ccgp.fetch_list(info_type="结果公告", page_num=1, start_date=start_dt, end_date=end_dt),
    ]

    results = await asyncio.gather(gov_task, eng_task, *ccgp_tasks, return_exceptions=True)

    gov_items = results[0] if isinstance(results[0], list) else []
    eng_items = results[1] if isinstance(results[1], list) else []
    ccgp_intent = results[2] if isinstance(results[2], list) else []
    ccgp_notice = results[3] if isinstance(results[3], list) else []
    ccgp_result = results[4] if isinstance(results[4], list) else []

    all_tenders.extend(gov_items)
    all_tenders.extend(eng_items)
    all_tenders.extend(ccgp_intent)
    all_tenders.extend(ccgp_notice)
    all_tenders.extend(ccgp_result)

    logger.info(f"  → 政府采购: {len(gov_items)} 条，工程招投标: {len(eng_items)} 条")
    logger.info(f"  → CCGP: 意向{len(ccgp_intent)} 条/公告{len(ccgp_notice)} 条/结果{len(ccgp_result)} 条")

    # 写入数据库（upsert）
    if all_tenders:
        rows = [tender_to_row(t) for t in all_tenders if t.url]
        if rows:
            try:
                db.upsert_projects(rows)
                logger.info(f"  ✅ DB 写入: {len(rows)} 条")
            except Exception as e:
                logger.error(f"  ❌ DB 写入失败: {e}")

    return all_tenders


async def run_batch(start_str: str, end_str: str):
    """批量采集 start ~ end 日期范围的数据"""
    start_dt = datetime.strptime(start_str, "%Y-%m-%d")
    end_dt = datetime.strptime(end_str, "%Y-%m-%d")

    months = []
    current = datetime(start_dt.year, start_dt.month, 1)
    while current <= end_dt:
        months.append((current.year, current.month))
        if current.month == 12:
            current = datetime(current.year + 1, 1, 1)
        else:
            current = datetime(current.year, current.month + 1, 1)

    logger.info(f"📂 待采集月份：{months}")

    browser = None
    try:
        browser = StealthBrowser(headless=settings.HEADLESS, slow_mo=settings.SLOW_MO)
        await browser.start()

        db = get_db()
        cqggzy = CQGGZYCrawlerV2(browser)
        ccgp = CCGPCrawlerV3(browser)

        total = 0
        for year, month in months:
            items = await collect_month(db, cqggzy, ccgp, year, month)
            total += len(items)
            logger.info(f"✅ {year}-{month:02d} 完成：{len(items)} 条（累计 {total} 条）")

        logger.info(f"🎉 全部完成，累计 {total} 条")

    except Exception as e:
        logger.error(f"❌ 批量采集失败：{e}")
        import traceback; traceback.print_exc()
    finally:
        if browser:
            await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="历史数据回填")
    parser.add_argument("--start", required=True, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")
    args = parser.parse_args()

    asyncio.run(run_batch(args.start, args.end))