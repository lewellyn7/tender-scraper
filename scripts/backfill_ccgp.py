#!/usr/bin/env python3
"""
CCGP 历史数据回填脚本 - 2026年1~5月
用法: python scripts/backfill_ccgp.py
"""
import asyncio, sys, os
from datetime import datetime

sys.path.insert(0, '/app')
os.environ['DATABASE_URL'] = 'postgresql://root:root123@postgres:5432/tender_scraper'

from app.core.browser import StealthBrowser
from app.crawlers.ccgp import CCGPCrawlerV3
from app.database.db import Database

START_DATE = datetime(2026, 1, 1)
END_DATE = datetime(2026, 5, 31)
INFO_TYPES = ['采购公告', '结果公告']
MAX_PAGES = 500

async def backfill_info_type(browser, info_type: str, db: Database):
    print(f'\n{"="*60}')
    print(f'回填: {info_type} ({START_DATE.date()} ~ {END_DATE.date()})')
    print(f'{"="*60}')

    crawler = CCGPCrawlerV3(browser)
    total_items = 0
    total_pages = 0

    for page_num in range(1, MAX_PAGES + 1):
        try:
            items = await crawler.fetch_list(
                info_type=info_type,
                page_num=page_num,
                start_date=START_DATE,
                end_date=END_DATE
            )

            if not items:
                print(f'  第{page_num}页: 0 条，停止')
                break

            for item in items:
                try:
                    db.upsert_projects_ccgp({
                        "url": item.url,
                        "title": item.title,
                        "category": getattr(item, 'category', ''),
                        "info_type": getattr(item, 'info_type', info_type),
                        "publish_date": getattr(item, 'publish_date', None),
                        "publish_date_raw": getattr(item, 'publish_date_raw', ''),
                        "source_url": item.url,
                        "scraped_by": "ccgp",
                    })
                    total_items += 1
                except Exception:
                    pass

            total_pages += 1
            print(f'  第{page_num}页: {len(items)} 条 (累计 {total_items})')

            if page_num % 20 == 0:
                print(f'  [进度] 第{page_num}页, 累计 {total_items} 条')

            await asyncio.sleep(0.5)

        except Exception as e:
            print(f'  第{page_num}页出错: {e}')
            await asyncio.sleep(3)
            continue

    print(f'{info_type} 完成: {total_pages} 页, {total_items} 条')
    return total_items

async def main():
    print(f'''
╔══════════════════════════════════════════════════════╗
║   CCGP 2026年1~5月历史数据回填                        ║
║   时间范围: {START_DATE.date()} ~ {END_DATE.date()}                      ║
╚══════════════════════════════════════════════════════╝
''')

    browser = StealthBrowser(headless=True, slow_mo=5)
    await browser.start()
    db = Database()

    grand_total = 0
    for info_type in INFO_TYPES:
        count = await backfill_info_type(browser, info_type, db)
        grand_total += count
        await asyncio.sleep(5)

    await browser.close()
    print(f'\n回填完成! 总计: {grand_total} 条记录')

if __name__ == '__main__':
    asyncio.run(main())