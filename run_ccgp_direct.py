#!/usr/bin/env python3
"""重庆政府采购网 - 下午 18 点采集任务"""
import asyncio
import sys
import json
from datetime import datetime

sys.path.insert(0, '/home/lewellyn/tender-scraper')

from app.crawlers.ccgp import CCGPCrawlerV3
from app.utils.report import ReportGenerator
from app.models.tender import TenderInfo

KEYWORDS = ["智能化", "音视频", "AI", "人工智能", "智能体", "大模型"]

def matches_keywords(title: str) -> bool:
    t = title.lower()
    for kw in KEYWORDS:
        if kw.lower() in t:
            return True
    return False

async def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"📅 采集日期: {today}")
    print(f"🔑 关键词: {KEYWORDS}")
    print()

    crawler = CCGPCrawlerV3()

    all_items = []
    for info_type, url in crawler.LIST_URLS.items():
        print(f"📋 采集 [{info_type}]...")
        items = await crawler.fetch_list(info_type)
        print(f"  → 获取 {len(items)} 条")
        all_items.extend(items)

    print(f"\n📥 总计: {len(all_items)} 条")

    # 过滤今日 + 关键词
    matched = []
    for item in all_items:
        if item.publish_date and today in str(item.publish_date):
            if matches_keywords(item.title):
                matched.append(item)
                print(f"  ✅ 匹配: {item.title[:60]}")

    print(f"\n🔍 今日关键词匹配: {len(matched)}/{len(all_items)} 条")

    if matched:
        print("\n📄 开始采集详情...")
        results = []
        for item in matched:
            detail = await crawler.fetch_detail(item)
            results.append(detail)

        # 生成 Excel
        rg = ReportGenerator(output_dir='/home/lewellyn/tender-scraper/output')
        excel_path = rg.generate_excel(results, f"ccgp_{today.replace('-','')}")
        print(f"\n✅ Excel: {excel_path}")

        # 输出摘要
        for r in results:
            print(f"\n【{r.info_type}】{r.title}")
            if r.budget:
                print(f"  预算: {r.budget}")
            if r.project_overview:
                print(f"  概况: {r.project_overview[:100]}")
            print(f"  链接: {r.url}")
    else:
        print("\n⚠️ 无今日匹配数据")
        # 保存空结果
        empty_data = {
            "total": len(all_items),
            "filtered": 0,
            "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "matched_projects": [],
            "message": f"今日({today})无符合关键词的采购信息"
        }
        with open('/home/lewellyn/.openclaw/workspace/logs/procurement/ccgp_latest.json', 'w') as f:
            json.dump(empty_data, f, ensure_ascii=False, indent=2)
        print(f"📊 JSON: /home/lewellyn/.openclaw/workspace/logs/procurement/ccgp_latest.json")

if __name__ == "__main__":
    asyncio.run(main())
