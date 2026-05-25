#!/usr/bin/env python3
"""重庆政府采购网 - 18点采集任务 (修复版)
- domcontentloaded 替代 networkidle
- 修复 report.py NaN 问题
- 修复 popup URL 捕获闭包问题
"""
import asyncio
import sys
import json
import os
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, '/home/lewellyn/tender-scraper')

from loguru import logger
from app.core.browser import StealthBrowser
from app.crawlers.ccgp import CCGPCrawlerV3
from app.models.tender import TenderInfo
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
        browser = StealthBrowser(headless=True, slow_mo=50)
        await browser.start()
        crawler = CCGPCrawlerV3(browser)
        crawler._visited_urls.clear()

        # === Step 1: 列表页采集 ===
        print("📋 Step 1: 采集列表页...")
        list_url = "https://www.ccgp-chongqing.gov.cn/gkw/web/portal/intention/list"
        page = await browser.new_page()
        logger.info(f"📄 采集列表：{list_url}")
        await page.goto(list_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)

        items = await page.query_selector_all(".block-item")
        print(f"  → 列表页获取 {len(items)} 条")

        all_items = []
        for i, item in enumerate(items):
            try:
                title_elem = await item.query_selector(".item-title")
                title = ((await title_elem.get_attribute("title")) or "").strip() if title_elem else ""
                date_elem = await item.query_selector(".date")
                item_date = (await date_elem.text_content() or "").strip() if date_elem else ""

                if not title:
                    continue

                # 通过点击获取详情 URL
                popup_info = {"url": None}

                def make_handler(info):
                    def handler(p):
                        if info["url"] is None and "info-notice" in p.url:
                            info["url"] = p.url
                            p.close()
                    return handler

                cb = make_handler(popup_info)
                page.on("popup", cb)
                try:
                    await item.click()
                    await asyncio.sleep(2)
                finally:
                    page.remove_listener("popup", cb)

                tender_info = TenderInfo(
                    title=title,
                    url=popup_info["url"] or list_url,
                    info_type="采购意向",
                    publish_date=item_date,
                )
                all_items.append(tender_info)

                kw_match = "✅" if matches_keywords(title) else "  "
                url_status = "✅" if popup_info["url"] else "⚠️"
                print(f"  {kw_match} {url_status} {item_date} | {title[:60]}")
                if popup_info["url"]:
                    print(f"         URL: {popup_info['url']}")
            except Exception as e:
                print(f"  ❌ 第 {i+1} 条失败: {e}")

        await page.close()
        print(f"\n📥 有效条目: {len(all_items)} 条")

        # 今日过滤
        today_items = [item for item in all_items if today in str(item.publish_date or "")]
        matched = [item for item in today_items if matches_keywords(item.title)]
        print(f"\n🔍 今日关键词命中: {len(matched)} 条")

        if matched:
            print(f"\n🎯 关键词命中:")
            for item in matched:
                kws = [kw for kw in KEYWORDS if kw.lower() in item.title.lower()]
                print(f"  • [{item.info_type}] {item.publish_date} | {item.title}")
                print(f"    关键词: {kws}")

        # === Step 2: 详情采集 ===
        targets = matched if matched else today_items
        if targets:
            print(f"\n📄 Step 2: 采集 {len(targets)} 个详情页...")
            results = []
            for i, item in enumerate(targets, 1):
                if item.url and "info-notice" in item.url:
                    print(f"  [{i}/{len(targets)}] {item.title[:50]}...")
                    detail = await crawler.fetch_detail(item)
                    results.append(detail)
                else:
                    print(f"  [{i}/{len(targets)}] 无详情URL，跳过: {item.title[:50]}")
                    results.append(item)

            # 生成 Excel
            output_dir = '/home/lewellyn/tender-scraper/output'
            os.makedirs(output_dir, exist_ok=True)
            rg = ReportGenerator(output_dir=output_dir)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            excel_path = rg.generate_excel(results, f"ccgp_日报_{today_short}")
            print(f"\n✅ Excel: {excel_path}")
        else:
            results = []
            excel_path = None
            print("\n⚠️ 今日无数据")

        # 保存 JSON
        json_dir = '/home/lewellyn/.openclaw/workspace/logs/procurement'
        os.makedirs(json_dir, exist_ok=True)
        json_path = os.path.join(json_dir, 'ccgp_latest.json')
        json_data = {
            "total": len(all_items),
            "today_items": len(today_items),
            "matched": len(matched),
            "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "excel": excel_path,
            "projects": [
                {
                    "title": r.title,
                    "info_type": r.info_type,
                    "budget": r.budget or "",
                    "region": r.region or "",
                    "url": r.url,
                    "publish_date": str(r.publish_date) if r.publish_date else "",
                    "keywords_matched": [kw for kw in KEYWORDS if kw.lower() in r.title.lower()],
                }
                for r in results
            ]
        }
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        print(f"📊 JSON: {json_path}")

        if not matched:
            print("\n📭 今日无关键词命中（智能化/音视频/AI/人工智能/智能体/大模型）")
            print("📝 已采集今日全部公告作为日报备查")

    finally:
        if browser:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())