#!/usr/bin/env python3
"""快速采集今日重庆政府采购网公告 - Playwright直接提取"""
import asyncio
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, '/home/lewellyn/tender-scraper')

from playwright.async_api import async_playwright
from app.utils.report import ReportGenerator

KEYWORDS = ["智能化", "音视频", "AI", "人工智能", "智能体", "大模型", "数智化"]
OUTPUT_DIR = "/home/lewellyn/.openclaw/workspace/logs/procurement"
os.makedirs(OUTPUT_DIR, exist_ok=True)

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

    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        )
        page = await ctx.new_page()

        # 采集采购公告
        print("📋 采集 [采购公告]...")
        await page.goto('https://www.ccgp-chongqing.gov.cn/info-notice/notice-list', timeout=60000)
        await asyncio.sleep(5)

        items = await page.query_selector_all('.block-item')
        print(f"  → 找到 {len(items)} 条")
        
        for item in items:
            try:
                title_elem = await item.query_selector('.item-title')
                if not title_elem:
                    continue
                title = (await title_elem.text_content() or '').strip()
                title = ' '.join(title.split())  # normalize whitespace
                
                date_elem = await item.query_selector('.date, .style__DateCol, [class*=DateCol]')
                date = (await date_elem.text_content() or '').strip() if date_elem else ''
                
                if today in date or today_short in date:
                    print(f"  今日: {title[:60]}")
                    if matches_keywords(title):
                        print(f"    ✅ 关键词匹配!")
                        results.append({
                            'title': title,
                            'url': f'https://www.ccgp-chongqing.gov.cn/info-notice/notice-list',
                            'business_type': '政府采购',
                            'info_type': '采购公告',
                            'publish_date': date,
                            'publish_date_raw': date,
                            'source_url': 'https://www.ccgp-chongqing.gov.cn/info-notice/notice-list',
                            'tender_type': '采购公告',
                            'budget': '',
                            'project_overview': title,
                            'contact_name': '',
                            'contact_phone': '',
                            'keywords_matched': [kw for kw in KEYWORDS if kw.lower() in title.lower()],
                        })
            except Exception as e:
                print(f"  提取失败: {e}")
                continue

        # 采集采购意向
        print("\n📋 采集 [采购意向]...")
        await page.goto('https://www.ccgp-chongqing.gov.cn/info-notice/intention-list', timeout=60000)
        await asyncio.sleep(5)

        items = await page.query_selector_all('.block-item')
        print(f"  → 找到 {len(items)} 条")
        
        for item in items:
            try:
                title_elem = await item.query_selector('.item-title')
                if not title_elem:
                    continue
                title = (await title_elem.text_content() or '').strip()
                title = ' '.join(title.split())
                
                date_elem = await item.query_selector('.date, .style__DateCol, [class*=DateCol]')
                date = (await date_elem.text_content() or '').strip() if date_elem else ''
                
                if today in date or today_short in date:
                    print(f"  今日: {title[:60]}")
                    if matches_keywords(title):
                        print(f"    ✅ 关键词匹配!")
                        results.append({
                            'title': title,
                            'url': f'https://www.ccgp-chongqing.gov.cn/info-notice/intention-list',
                            'business_type': '政府采购',
                            'info_type': '采购意向',
                            'publish_date': date,
                            'publish_date_raw': date,
                            'source_url': 'https://www.ccgp-chongqing.gov.cn/info-notice/intention-list',
                            'tender_type': '采购意向',
                            'budget': '',
                            'project_overview': title,
                            'contact_name': '',
                            'contact_phone': '',
                            'keywords_matched': [kw for kw in KEYWORDS if kw.lower() in title.lower()],
                        })
            except Exception as e:
                continue

        # 采集结果公告
        print("\n📋 采集 [结果公告]...")
        await page.goto('https://www.ccgp-chongqing.gov.cn/info-notice/result-list', timeout=60000)
        await asyncio.sleep(5)

        items = await page.query_selector_all('.block-item')
        print(f"  → 找到 {len(items)} 条")
        
        for item in items:
            try:
                title_elem = await item.query_selector('.item-title')
                if not title_elem:
                    continue
                title = (await title_elem.text_content() or '').strip()
                title = ' '.join(title.split())
                
                date_elem = await item.query_selector('.date, .style__DateCol, [class*=DateCol]')
                date = (await date_elem.text_content() or '').strip() if date_elem else ''
                
                if today in date or today_short in date:
                    print(f"  今日: {title[:60]}")
                    if matches_keywords(title):
                        print(f"    ✅ 关键词匹配!")
                        results.append({
                            'title': title,
                            'url': f'https://www.ccgp-chongqing.gov.cn/info-notice/result-list',
                            'business_type': '政府采购',
                            'info_type': '结果公告',
                            'publish_date': date,
                            'publish_date_raw': date,
                            'source_url': 'https://www.ccgp-chongqing.gov.cn/info-notice/result-list',
                            'tender_type': '结果公告',
                            'budget': '',
                            'project_overview': title,
                            'contact_name': '',
                            'contact_phone': '',
                            'keywords_matched': [kw for kw in KEYWORDS if kw.lower() in title.lower()],
                        })
            except Exception as e:
                continue

        await browser.close()

    print(f"\n📥 总计: {len(results)} 条关键词匹配")
    
    # 生成 Excel
    excel_path = ""
    if results:
        rg = ReportGenerator(OUTPUT_DIR)
        excel_path = rg.generate_excel(results, f"ccgp_procurement_{today_short}")
        print(f"✅ Excel: {excel_path}")
    else:
        print("⚠️ 无今日匹配数据")
    
    # 保存 JSON
    data_path = os.path.join(OUTPUT_DIR, "ccgp_latest.json")
    output_data = {
        "total": len(results),
        "filtered": len(results),
        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "matched_projects": results,
    }
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"📊 JSON: {data_path}")
    
    # 打印摘要
    print("\n" + "="*60)
    if results:
        for r in results:
            print(f"【{r['info_type']}】{r['title'][:60]}")
            print(f"  日期: {r['publish_date']} | 关键词: {r['keywords_matched']}")
    else:
        print("今日无符合关键词的采购信息")
    print("="*60)
    
    return len(results)

if __name__ == "__main__":
    count = asyncio.run(main())
    sys.exit(0 if count > 0 else 0)
