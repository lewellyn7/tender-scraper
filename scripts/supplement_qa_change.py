"""补采答疑变更 + 相关公告（2026-01-01~2026-05-31）

采集策略：
- gov_purchase 列表页 → 点击"答疑变更"页签 → 滚动收集所有 014005002 条目
- engineering 列表页 → 点击"相关公告"页签 → 滚动收集所有 014001016 条目
- 每页10条，无翻页按钮，滚动到底即可
- 每分类最多50条
"""
import asyncio, os, sys, re, json
from datetime import datetime

sys.path.insert(0, '/app')
from playwright.async_api import async_playwright
from app.database import get_db

START = datetime(2026, 1, 1)
END   = datetime(2026, 5, 31)

def date_from_url(url: str):
    m = re.search(r'/(\d{4})(\d{2})(\d{2})/', url)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None

async def collect_tab(browser, url: str, tab_name: str, href_pattern: str, info_type: str, category: str, max_items=50):
    """切换页签并收集匹配 href_pattern 的条目"""
    page = await browser.new_page()
    results = []
    try:
        await page.goto(url, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(2)

        # 点击目标页签
        tabs = await page.query_selector_all('.tab-tt li')
        for tab in tabs:
            txt = (await tab.text_content()).strip()
            if txt == tab_name:
                await tab.click()
                await asyncio.sleep(2)
                break
        else:
            print(f"  ⚠ 未找到页签: {tab_name}")
            return results

        seen = set()
        for _ in range(8):  # 最多滚动8次（80条）
            if len(results) >= max_items:
                break

            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await asyncio.sleep(0.5)

            items = await page.query_selector_all('.tab-bd li')
            for item in items:
                link = await item.query_selector('a')
                if not link:
                    continue
                href = await link.get_attribute('href') or ''
                title = (await link.text_content() or '').strip()

                if href_pattern not in href or href in seen or len(title) < 8:
                    continue

                date = date_from_url(href)
                if date and date < START:
                    break  # 超出日期范围

                seen.add(href)
                full_url = href if href.startswith('http') else f'https://www.cqggzy.com{href}'
                results.append({
                    'url': full_url,
                    'title': title,
                    'date': date,
                    'info_type': info_type,
                    'category': category,
                    'source_url': url,
                })
                print(f"  [{info_type}] {date.date() if date else '?'} {title[:40]}")

                if len(results) >= max_items:
                    break

        print(f"  {info_type}: {len(results)} 条")
    except Exception as e:
        print(f"  ⚠ {info_type} error: {e}")
    finally:
        await page.close()
    return results


async def main():
    print("=== 补采答疑变更 + 相关公告 ===\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch()

        print("[1] 政府采购 - 答疑变更...")
        change = await collect_tab(
            browser,
            'https://www.cqggzy.com/xxhz/014005/order.html',
            '答疑变更', '014005002', '答疑变更', '政府采购'
        )

        print("\n[2] 工程招投标 - 相关公告...")
        related = await collect_tab(
            browser,
            'https://www.cqggzy.com/xxhz/014001/bidding.html',
            '相关公告', '014001016', '相关公告', '工程建设'
        )

        await browser.close()

    all_items = change + related
    print(f"\n合计: {len(all_items)} 条\n")

    if not all_items:
        print("无新数据")
        return

    # 写入 DB
    print("[3] 写入数据库...")
    db = get_db()
    rows = []
    for item in all_items:
        date = item.get('date') or datetime(2026, 1, 1)
        rows.append({
            'url': item['url'],
            'title': item['title'][:500],
            'category': item['category'],
            'info_type': item['info_type'],
            'business_type': item['category'],
            'publish_date': date,
            'publish_date_raw': date.strftime('%Y-%m-%d') if isinstance(date, datetime) else '',
            'content_preview': item['title'][:500],
            'full_content': '',
            'budget': '',
            'bid_amount': '',
            'deadline': None,
            'region': '重庆市',
            'industry': '',
            'tender_type': item['category'],
            'project_overview': '',
            'bidder_requirements': '',
            'submission_deadline': '',
            'contact_name': '',
            'contact_phone': '',
            'contact_email': '',
            'attachments_count': 0,
            'attachments': '[]',
            'keywords_matched': '',
            'source_url': item.get('source_url', ''),
            'scraped_at': None,
            'scraped_by': 'supplement_v2',
            'contract_amount': '',
            'planned_publish_date': '',
            'tender_content': '',
            'opening_date': None,
        })

    db.upsert_projects(rows)
    print(f"  写入 {len(rows)} 条")

    try:
        import httpx
        web_url = os.getenv("WEB_URL", "http://tender-scraper-web:8000")
        cache_key = os.getenv("INTERNAL_CACHE_CLEAR_KEY", "")
        httpx.post(f"{web_url}/api/cache/clear", json={"internal_key": cache_key}, timeout=5)
    except Exception:
        pass

    print("\n✅ 补采完成")


if __name__ == '__main__':
    asyncio.run(main())