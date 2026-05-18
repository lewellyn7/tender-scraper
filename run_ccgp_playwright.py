#!/usr/bin/env python3
"""重庆政府采购网 - 使用 Playwright 绕过超时（等待 load 而非 networkidle）"""
import asyncio
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, '/home/lewellyn/tender-scraper')

from playwright.async_api import async_playwright
from app.utils.report import ReportGenerator

KEYWORDS = ["智能化", "音视频", "AI", "人工智能", "智能体", "大模型"]
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

        # 设置更长的超时，使用 load 事件而非 networkidle
        timeout = 90000  # 90 秒

        pages = [
            ("采购公告", "https://www.ccgp-chongqing.gov.cn/gkw/web/portal/notice/list"),
            ("采购意向", "https://www.ccgp-chongqing.gov.cn/gkw/web/portal/intention/list"),
            ("结果公告", "https://www.ccgp-chongqing.gov.cn/gkw/web/portal/result/list"),
        ]

        for info_type, url in pages:
            print(f"📋 采集 [{info_type}]...")
            try:
                response = await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
                print(f"  Status: {response.status if response else 'None'}")

                # 等待内容加载
                await page.wait_for_timeout(8000)

                # 尝试多种选择器
                items = []
                for selector in [
                    '.block-item',
                    '.notice-item',
                    '.list-item',
                    '[class*="item"]',
                    '.gk-list-item',
                    '.portal-list-item',
                ]:
                    found = await page.query_selector_all(selector)
                    if found:
                        items = found
                        print(f"  找到 {len(items)} 条 ({selector})")
                        break

                if not items:
                    # 打印页面当前状态
                    count = await page.query_selector_all('div')
                    print(f"  页面有 {len(count)} 个 div")
                    # 截图保存调试
                    await page.screenshot(path=f'/tmp/ccgp_debug_{info_type}.png')
                    print(f"  截图: /tmp/ccgp_debug_{info_type}.png")

                for item in items[:20]:
                    try:
                        # 尝试多种方式获取标题
                        title = ''
                        for sel in ['.item-title', '.title', 'a', '.notice-title', '[class*="title"]']:
                            te = await item.query_selector(sel)
                            if te:
                                title = (await te.text_content() or '').strip()
                                if title:
                                    break

                        if not title:
                            continue

                        title = ' '.join(title.split())  # 规范化空白

                        # 日期
                        date = ''
                        for sel in ['.date', '[class*="date"]', '.time']:
                            de = await item.query_selector(sel)
                            if de:
                                date = (await de.text_content() or '').strip()
                                break

                        if not date:
                            text = await item.text_content()
                            import re
                            m = re.search(r'(\d{4}-\d{2}-\d{2})', text or '')
                            if m:
                                date = m.group(1)

                        # 过滤：今日 + 关键词
                        if (today not in date and today_short not in date):
                            continue

                        if not matches_keywords(title):
                            continue

                        # 链接
                        link = await item.query_selector('a')
                        href = ''
                        if link:
                            href = await link.get_attribute('href') or ''
                            if href.startswith('/'):
                                href = 'https://www.ccgp-chongqing.gov.cn' + href
                            elif not href.startswith('http'):
                                href = 'https://www.ccgp-chongqing.gov.cn/' + href

                        matched_kw = [kw for kw in KEYWORDS if kw.lower() in title.lower()]
                        results.append({
                            'title': title,
                            'url': href,
                            'business_type': '政府采购',
                            'info_type': info_type,
                            'publish_date': date,
                            'publish_date_raw': date,
                            'source_url': url,
                            'tender_type': info_type,
                            'budget': '',
                            'project_overview': title,
                            'contact_name': '',
                            'contact_phone': '',
                            'keywords_matched': matched_kw,
                        })
                        print(f"  ✅ {matched_kw[0]} | {title[:50]}")
                    except Exception as e:
                        print(f"  提取失败: {e}")
                        continue

            except Exception as e:
                print(f"  ❌ [{info_type}] 加载失败: {e}")
                await page.screenshot(path=f'/tmp/ccgp_err_{info_type}.png')

        await browser.close()

    print(f"\n📥 关键词匹配: {len(results)} 条")

    # 生成 Excel
    excel_path = ""
    if results:
        rg = ReportGenerator(OUTPUT_DIR)
        excel_path = rg.generate_excel(results, f"ccgp_procurement_{today_short}")
        print(f"✅ Excel: {excel_path}")
    else:
        print("⚠️ 今日无匹配数据")

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
    sys.exit(0)