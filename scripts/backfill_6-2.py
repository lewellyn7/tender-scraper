#!/usr/bin/env python3
"""
一次性补采脚本：补回 6-2 ~ 6-3 期间因 main.py 只采第 1 页而丢失的数据
日期范围：5-24 ~ 6-3（覆盖 6-2 那次完整窗口 + 6-3 当天）
分类：9 个细分分类（与 main.py 一致）
ON CONFLICT (url) DO UPDATE：重复 URL 会被覆盖，不会插重
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

START_DATE = datetime(2026, 5, 24)
END_DATE = datetime(2026, 6, 3)
MAX_PAGES = 20  # 每分类最多 20 页（1000 条）安全保护

# 9 个细分分类（与 main.py 第 142-152 行一致）
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
    print(f'\n{"="*60}')
    print(f'  补采: {category} ({START_DATE.date()} ~ {END_DATE.date()})')
    print(f'{"="*60}')

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
                        # 2026-06-03 修复：必须传 scraped_at，否则 ON CONFLICT DO UPDATE 会把已存在的 scraped_at 置 NULL
                        "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "scraped_by": getattr(item, 'scraped_by', 'tender-scraper v3.2 (backfill-6-2)'),
                    }
                    db.upsert_projects([row])
                except Exception as e:
                    print(f'    写入失败: {e}')

            total_items += len(items)
            print(f'  第{page_num}页: {len(items)} 条 (累计 {total_items})')

            if len(items) == 0:
                print(f'  -> 无数据，停止')
                break
            if len(items) < 50:
                print(f'  -> 不足 50 条，已到末页')
                break

            await asyncio.sleep(0.5)
        except Exception as e:
            print(f'  第{page_num}页异常: {e}')
            await asyncio.sleep(3)
            continue

    return total_items


async def main():
    print(f'''
╔══════════════════════════════════════════════════════╗
║   一次性补采 6-2 ~ 6-3 丢失数据                       ║
║   时间范围: {START_DATE.date()} ~ {END_DATE.date()}                    ║
║   分类数: {len(CATEGORIES)}                                       ║
╚══════════════════════════════════════════════════════╝
''')

    browser = StealthBrowser(headless=True, slow_mo=5)
    await browser.start()
    db = Database()

    grand_total = 0
    for category in CATEGORIES:
        try:
            count = await backfill_category(browser, category, db)
            grand_total += count
        except Exception as e:
            print(f'  {category} 失败: {e}')
        await asyncio.sleep(2)

    await browser.close()
    print(f'\n✅ 补采完成! 总计入库: {grand_total} 条')


if __name__ == '__main__':
    asyncio.run(main())
