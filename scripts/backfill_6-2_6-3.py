#!/usr/bin/env python3
"""
一次性补采 6-2 和 6-3 全部项目（不限关键词）
- 9 个分类全量采集
- API edt 是排他的：sdt=6-2, edt=6-4 才能包含 6-2 和 6-3
- ON CONFLICT (url) DO UPDATE 不会插重
"""
import asyncio
import sys
import os
from datetime import datetime

sys.path.insert(0, '/app')
os.environ.setdefault('DATABASE_URL', 'postgresql://root:root123@postgres:5432/tender_scraper')

from app.core.browser import StealthBrowser
from app.crawlers.cqggzy import CQGGZYCrawlerV2 as CQGGZYCrawler
from app.database.db import Database

# 2026-06-05 修复：API edt 排他，传 edt=6-4 才能采到 6-3 当天
START_DATE = datetime(2026, 6, 2)
END_DATE = datetime(2026, 6, 4)  # 排他 → 实际采集 6-2 和 6-3
MAX_PAGES = 20

CATEGORIES = [
    "engineering_notice",
    "engineering_plan",
    "engineering_qa",
    "engineering_candidate",
    "engineering_result",
    "engineering_terminate",
    "gov_purchase_notice",
    "gov_purchase_change",
    "gov_purchase_result",
]


async def backfill_category(browser, category: str, db: Database):
    crawler = CQGGZYCrawler(browser)
    total_items = 0
    for page_num in range(1, MAX_PAGES + 1):
        try:
            items = await crawler.fetch_list(
                category=category,
                page_num=page_num,
                start_date=START_DATE,
                end_date=END_DATE,
            )
            if not isinstance(items, list):
                items = []
            for item in items:
                try:
                    row = {
                        "url": item.url,
                        "title": item.title,
                        "category": item.category,
                        "info_type": item.tender_type,
                        "publish_date": getattr(item, 'publish_date', None),
                        "publish_date_raw": getattr(item, 'publish_date_raw', ''),
                        "source_url": item.source_url,
                        "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "scraped_by": 'tender-scraper v3.2 (backfill-6-2_6-3)',
                    }
                    db.upsert_projects([row])
                except Exception as e:
                    print(f'    写入失败: {e}')
            total_items += len(items)
            print(f'  {category} p{page_num}: {len(items)} (累计 {total_items})', flush=True)
            if len(items) == 0 or len(items) < 50:
                break
            await asyncio.sleep(0.3)
        except Exception as e:
            print(f'  {category} p{page_num} 异常: {e}')
            await asyncio.sleep(3)
            continue
    return total_items


async def main():
    print(f'\n[6-2/6-3 全量补采] {START_DATE.date()} ~ {END_DATE.date()} (实际采 6-2+6-3)\n', flush=True)
    browser = StealthBrowser(headless=True, slow_mo=5)
    await browser.start()
    db = Database()
    grand_total = 0
    per_cat = {}
    for category in CATEGORIES:
        try:
            count = await backfill_category(browser, category, db)
            per_cat[category] = count
            grand_total += count
        except Exception as e:
            print(f'  {category} 失败: {e}')
        await asyncio.sleep(1)
    await browser.close()
    print(f'\n=== 完成 ===')
    for k, v in per_cat.items():
        print(f'  {k}: {v}')
    print(f'  总计: {grand_total}')


if __name__ == '__main__':
    asyncio.run(main())
