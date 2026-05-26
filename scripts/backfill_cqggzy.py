#!/usr/bin/env python3
"""
CQGGZY 历史数据回填脚本 - 2026年1~5月
用法: python scripts/backfill_cqggzy.py
"""
import asyncio, sys, os
from datetime import datetime

sys.path.insert(0, '/app')
os.environ['DATABASE_URL'] = 'postgresql://root:root123@postgres:5432/tender_scraper'

from app.core.browser import StealthBrowser
from app.crawlers.cqggzy import CQGGZYCrawlerV2 as CQGGZYCrawler
from app.database.db import Database

START_DATE = datetime(2026, 1, 1)
END_DATE = datetime(2026, 5, 31)
CATEGORY_MAP = {
    '工程招投标': 'engineering',
    '政府采购': 'gov_purchase',
}
MAX_PAGES = 200

async def backfill_category(browser, category: str, db: Database):
    internal = CATEGORY_MAP.get(category, category)
    print(f'\n{"="*60}')
    print(f'回填: {category} ({START_DATE.date()} ~ {END_DATE.date()})')
    print(f'{"="*60}')

    crawler = CQGGZYCrawler(browser)
    total_items = 0

    for page_num in range(1, MAX_PAGES + 1):
        try:
            items = await crawler.fetch_list(
                category=internal,
                page_num=page_num,
                start_date=START_DATE,
                end_date=END_DATE
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
                        "scraped_by": getattr(item, 'scraped_by', ''),
                    }
                    db.upsert_projects([row])
                except Exception as e:
                    print(f'  写入失败: {e}')

            total_items += len(items)
            print(f'  第{page_num}页: {len(items)} 条')

            if len(items) == 0:
                print(f'  -> 无数据，停止')
                break

            if page_num % 10 == 0:
                print(f'  [进度] 第{page_num}页, 累计 {total_items} 条')

            await asyncio.sleep(0.5)

        except Exception as e:
            print(f'  第{page_num}页出错: {e}')
            await asyncio.sleep(3)
            continue

    print(f'{category} 完成: {total_items} 条')
    return total_items

async def main():
    print(f'''
╔══════════════════════════════════════════════════════╗
║   CQGGZY 2026年1~5月历史数据回填                     ║
║   时间范围: {START_DATE.date()} ~ {END_DATE.date()}                      ║
╚══════════════════════════════════════════════════════╝
''')

    browser = StealthBrowser(headless=True, slow_mo=5)
    await browser.start()
    db = Database()

    grand_total = 0
    for category in ['工程招投标', '政府采购']:
        count = await backfill_category(browser, category, db)
        grand_total += count
        await asyncio.sleep(5)

    await browser.close()
    print(f'\n回填完成! 总计: {grand_total} 条记录')

if __name__ == '__main__':
    asyncio.run(main())