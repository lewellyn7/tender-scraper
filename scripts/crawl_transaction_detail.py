#!/usr/bin/env python3
"""
CQGGZY 全分类翻页采集
"""
import asyncio, sys, os, json
from datetime import datetime
from urllib.parse import urljoin

sys.path.insert(0, '/app')
os.environ['DATABASE_URL'] = 'postgresql://root:root123@postgres:5432/tender_scraper'

from app.core.browser import StealthBrowser
from app.database.db import Database

BASE = "https://www.cqggzy.com"
CATEGORIES = [
    ("014001001", "招标公告"),
    ("014001003", "中标结果公示"),
    ("014001004", "中标候选人公示"),
    ("014005001", "采购公告"),
    ("014005002", "采购结果公告"),
]
START = datetime(2026, 1, 1)
END = datetime(2026, 5, 31)

def parse(captured):
    if not captured:
        return []
    try:
        outer = json.loads(captured[-1])
        inner = json.loads(outer['content'])
        return inner['result'].get('records', [])
    except:
        return []

def write(records, cat_num, info_type):
    if not records:
        return 0
    db = Database()
    written = 0
    for rec in records:
        title = rec.get('title', '') or rec.get('titlenew', '')
        linkurl = rec.get('linkurl', '')
        if not linkurl or not title:
            continue
        if linkurl.startswith('/'):
            linkurl = urljoin(BASE, linkurl)
        webdate = rec.get('webdate', '') or rec.get('pubinwebdate', '') or ''
        try:
            dt = datetime.strptime(webdate[:10], '%Y-%m-%d') if webdate else None
        except:
            dt = None
        if dt and (dt < START or dt > END):
            continue
        date_str = str(dt.date()) if dt else ''
        db.upsert_projects([{
            "url": linkurl,
            "title": title,
            "category": cat_num,
            "info_type": info_type,
            "publish_date": dt,
            "publish_date_raw": date_str,
            "source_url": linkurl,
            "scraped_by": "cqggzy_full",
        }])
        written += 1
    return written

def js_click_page(page_num):
    return """
var pages = document.querySelectorAll('.pagination a');
for (var i = 0; i < pages.length; i++) {
    var t = pages[i].textContent.trim();
    if (t == '%d') { pages[i].click(); return true; }
}
return false;
    """ % (page_num + 1)

async def scrape_category(browser, cat_num, info_type):
    page = await browser.new_page()
    captured = []

    async def on_resp(resp):
        if 'inteligentsearch' in resp.url:
            try:
                body = await resp.text()
                captured.append(body)
            except:
                pass

    if cat_num.startswith('014005'):
        url = BASE + "/xxhz/014005/" + cat_num + "/transaction_detail.html"
    else:
        url = BASE + "/xxhz/014001/" + cat_num + "/transaction_detail.html"

    page.on('response', on_resp)
    await page.goto(url, wait_until='domcontentloaded', timeout=30000)
    await asyncio.sleep(3)

    total = 0
    records = parse(captured)
    if records:
        try:
            outer = json.loads(captured[-1])
            inner = json.loads(outer['content'])
            total = inner['result'].get('totalcount', 0)
        except:
            pass

    print("  [%s] total=%d" % (info_type, total))
    written = write(records, cat_num, info_type)
    print("  第1页: +%d -> 累计 %d" % (len(records), written))
    captured.clear()

    page_num = 1
    while True:
        clicked = await page.evaluate(js_click_page(page_num))

        if not clicked:
            print("  找不到第%d页，停止" % (page_num + 1))
            break

        await asyncio.sleep(2)
        records = parse(captured)
        if not records:
            print("  第%d页: 0条/无响应，停止" % (page_num + 1))
            break

        w = write(records, cat_num, info_type)
        written += w
        print("  第%d页: +%d -> 累计 %d" % (page_num + 1, len(records), written))
        captured.clear()
        page_num += 1

        if page_num > 100:
            print("  安全限制(100页)")
            break

    await page.close()
    return written, total

async def main():
    print("╔═══════════════════════════════════════════════╗")
    print("║  CQGGZY 全分类采集  2026-01-01~2026-05-31   ║")
    print("╚═══════════════════════════════════════════════╝")

    browser = StealthBrowser(headless=True, slow_mo=5)
    await browser.start()
    grand = 0

    for cat_num, info_type in CATEGORIES:
        print("\n▶ %s (%s)" % (info_type, cat_num))
        written, total = await scrape_category(browser, cat_num, info_type)
        print("  → %d 条写入 / 网站 %d 条" % (written, total))
        grand += written

    await browser.close()
    print("\n总计: %d 条写入" % grand)

asyncio.run(main())