#!/usr/bin/env python3
"""
CQGGZY 按日回填脚本 - 2026年1~5月
每天单独爬取，避免分页重叠导致的数据遗漏
"""
import asyncio, sys, os
from datetime import datetime, timedelta

sys.path.insert(0, '/app')
os.environ['DATABASE_URL'] = 'postgresql://root:root123@postgres:5432/tender_scraper'

from app.core.browser import StealthBrowser
from app.crawlers.cqggzy import CQGGZYCrawlerV2 as CQGGZYCrawler
from app.database.db import Database

START = datetime(2026, 1, 1)
END = datetime(2026, 5, 31)
CATEGORY_MAP = {'工程招投标': 'engineering', '政府采购': 'gov_purchase'}
DAILY_LIMIT = 10  # 每天最多翻10页

def date_range(start, end):
    days = int((end - start).days) + 1
    for i in range(days):
        yield start + timedelta(days=i)

async def crawl_day(browser, date: datetime, category: str, db: Database):
    crawler = CQGGZYCrawler(browser)
    internal = CATEGORY_MAP[category]
    day_str = date.strftime('%Y-%m-%d')
    total = 0

    for page in range(1, DAILY_LIMIT + 1):
        items = await crawler.fetch_list(
            category=internal,
            page_num=page,
            start_date=date,
            end_date=date
        )
        if not isinstance(items, list):
            items = []

        for item in items:
            try:
                db.upsert_projects([{
                    "url": item.url,
                    "title": item.title,
                    "category": item.category,
                    "info_type": item.tender_type,
                    "publish_date": getattr(item, 'publish_date', None),
                    "publish_date_raw": getattr(item, 'publish_date_raw', ''),
                    "source_url": item.source_url,
                    "scraped_by": getattr(item, 'scraped_by', ''),
                }])
                total += 1
            except Exception:
                pass

        if len(items) == 0:
            break
        await asyncio.sleep(0.3)

    return total

async def main():
    total_days = 0
    total_items = 0
    browser = StealthBrowser(headless=True, slow_mo=5)
    await browser.start()
    db = Database()

    for category in ['工程招投标', '政府采购']:
        print(f'\n========== {category} ==========')
        for date in date_range(START, END):
            day_str = date.strftime('%Y-%m-%d')
            try:
                count = await crawl_day(browser, date, category, db)
                if count > 0:
                    print(f'  {day_str} {category}: +{count} 条')
                    total_items += count
                    total_days += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f'  {day_str} {category} 出错: {e}')
                await asyncio.sleep(2)
                continue

    await browser.close()
    print(f'\n完成: {total_days} 天有数据, 共 {total_items} 条新记录')

if __name__ == '__main__':
    asyncio.run(main())