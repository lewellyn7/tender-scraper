import asyncio, sys, os, json
from datetime import datetime
from urllib.parse import urljoin

sys.path.insert(0, '/app')
os.environ['DATABASE_URL'] = 'postgresql://root:root123@postgres:5432/tender_scraper'

from app.core.browser import StealthBrowser
from app.database.db import Database

BASE = "https://www.cqggzy.com"
CATEGORY = "014001019"
START = datetime(2026, 1, 1)
END = datetime(2026, 5, 31)

async def main():
    print(f'CQGGZY 招标计划 按月采集 {START.date()} ~ {END.date()}')

    browser = StealthBrowser(headless=True, slow_mo=5)
    await browser.start()
    page = await browser.new_page()

    captured_responses = []
    async def on_response(resp):
        if 'inteligentsearch' in resp.url:
            try:
                body = await resp.text()
                data = json.loads(body)
                captured_responses.append(data)
            except:
                pass

    page.on('response', on_response)

    # First: load page normally to get normal links
    await page.goto(f'{BASE}/xxhz/014001/{CATEGORY}/transaction_detail.html', wait_until='domcontentloaded', timeout=30000)
    await asyncio.sleep(3)

    # Collect all links from initial load
    all_links = {}
    links = await page.query_selector_all(f'a[href*="/014001/{CATEGORY}/202"]')
    for link in links:
        href = await link.get_attribute('href')
        title = await link.inner_text()
        if href and title.strip():
            date_match = href.split('/')[-2]
            date_str = f"{date_match[:4]}-{date_match[4:6]}-{date_match[6:8]}"
            all_links[href] = (title.strip(), date_str)

    # Check captured responses for total
    for data in captured_responses:
        if 'total' in data:
            print(f"API total: {data['total']}, results: {len(data.get('result',[]))}")

    print(f"Initial links: {len(all_links)}")

    # Now navigate through pages to get more links
    for pg in range(2, 100):
        clicked = await page.evaluate(f"""() => {{
            var pages = document.querySelectorAll('.pagination a, #pager a, .pager a');
            for (var i = 0; i < pages.length; i++) {{
                var txt = pages[i].textContent.trim();
                if (txt == '{pg}') {{
                    pages[i].click();
                    return true;
                }}
            }}
            return false;
        }}""")

        if not clicked:
            break

        await asyncio.sleep(2)

        links = await page.query_selector_all(f'a[href*="/014001/{CATEGORY}/202"]')
        old_count = len(all_links)
        for link in links:
            href = await link.get_attribute('href')
            title = await link.inner_text()
            if href and title.strip() and href not in all_links:
                date_match = href.split('/')[-2]
                date_str = f"{date_match[:4]}-{date_match[4:6]}-{date_match[6:8]}"
                all_links[href] = (title.strip(), date_str)

        new_count = len(all_links)
        print(f"  第{pg}页: +{new_count - old_count} new (total: {new_count})")

        if len(links) == 0:
            print(f"  -> 0 links, stop")
            break

    await browser.close()

    # Filter by date range
    filtered = {href: (title, date_str) for href, (title, date_str) in all_links.items()
                if START <= datetime.strptime(date_str, '%Y-%m-%d') <= END}

    print(f'\n总计: {len(all_links)} 条, 1-5月: {len(filtered)} 条')

    # Write to DB
    db = Database()
    written = 0
    for url, (title, date_str) in filtered.items():
        try:
            db.upsert_projects([{
                "url": url,
                "title": title,
                "category": CATEGORY,
                "info_type": "招标计划",
                "publish_date": datetime.strptime(date_str, '%Y-%m-%d'),
                "publish_date_raw": date_str,
                "source_url": url,
                "scraped_by": "cqggzy_direct",
            }])
            written += 1
        except:
            pass

    print(f'写入数据库: {written} 条')

if __name__ == '__main__':
    asyncio.run(main())