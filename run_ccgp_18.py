#!/usr/bin/env python3
"""重庆政府采购网 - 18点采集任务 (完整版)"""
import asyncio
import sys
import json
import os
from datetime import datetime

sys.path.insert(0, '/home/lewellyn/tender-scraper')

from app.core.browser import StealthBrowser
from app.crawlers.ccgp import CCGPCrawlerV3
from app.utils.report import ReportGenerator

KEYWORDS = ["智能化", "音视频", "AI", "人工智能", "智能体", "大模型"]

def matches_keywords(title: str) -> bool:
    t = title.lower()
    for kw in KEYWORDS:
        if kw.lower() in t:
            return True
    return False

async def main():
    today = datetime.now().strftime("%Y-%m-%d")
    today_short = datetime.now().strftime("%Y%m%d")
    print(f"📅 采集日期: {today}")
    print(f"🔑 关键词: {KEYWORDS}")
    print()

    browser = None
    try:
        browser = StealthBrowser(headless=True, slow_mo=100)
        await browser.start()
        crawler = CCGPCrawlerV3(browser)
        crawler._visited_urls.clear()  # 清空访问记录

        all_items = []
        for info_type in ["采购意向", "采购公告", "结果公告"]:
            print(f"📋 采集 [{info_type}]...")
            items = await crawler.fetch_list(info_type=info_type, page_num=1)
            print(f"  → 获取 {len(items)} 条")
            all_items.extend(items)

        print(f"\n📥 总计: {len(all_items)} 条")

        # 过滤今日 + 关键词
        matched = []
        for item in all_items:
            item_date = str(item.publish_date or '')
            if today in item_date or today_short in item_date:
                if matches_keywords(item.title):
                    matched.append(item)
                    print(f"  ✅ 匹配: {item.title[:60]}")

        print(f"\n🔍 今日关键词匹配: {len(matched)} 条")

        if matched:
            print(f"\n📄 开始采集 {len(matched)} 个详情页...")
            results = []
            for i, item in enumerate(matched, 1):
                print(f"  [{i}/{len(matched)}] {item.title[:50]}...")
                detail = await crawler.fetch_detail(item)
                results.append(detail)

            # 生成 Excel
            output_dir = '/home/lewellyn/tender-scraper/output'
            os.makedirs(output_dir, exist_ok=True)
            rg = ReportGenerator(output_dir=output_dir)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            excel_path = rg.generate_excel(results, f"ccgp_{timestamp}")
            print(f"\n✅ Excel: {excel_path}")

            # 保存 JSON
            json_dir = '/home/lewellyn/.openclaw/workspace/logs/procurement'
            os.makedirs(json_dir, exist_ok=True)
            json_path = os.path.join(json_dir, 'ccgp_latest.json')
            json_data = {
                "total": len(all_items),
                "matched": len(matched),
                "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "excel": excel_path,
                "projects": [
                    {
                        "title": r.title,
                        "info_type": r.info_type,
                        "budget": r.budget,
                        "region": r.region,
                        "url": r.url,
                        "publish_date": str(r.publish_date) if r.publish_date else '',
                    }
                    for r in results
                ]
            }
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=2)
            print(f"📊 JSON: {json_path}")

            # 输出摘要
            for r in results:
                print(f"\n【{r.info_type}】{r.title}")
                if r.budget:
                    print(f"  预算: {r.budget}")
                print(f"  链接: {r.url}")
        else:
            print("\n⚠️ 今日无匹配数据")

    finally:
        if browser:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())