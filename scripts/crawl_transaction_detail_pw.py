#!/usr/bin/env python3
"""
CQGGZY transaction_detail.html 全分类采集 (Playwright v2)

正确 DOM 结构:
  <ul id="showList">
    <li class="info-item">
      <a href="...url...">标题</a>
      <span>招标方式</span>
      <span>日期</span>
    </li>
  </ul>
分页: <div class="pagination"><a class="pageIdx">2</a> ...</div>
日期过滤: #dateSel1 (开始) #dateSel2 (结束)，laydate 组件
"""
import asyncio, sys, os, re, json
from datetime import datetime, date
from typing import List, Dict, Set

sys.path.insert(0, '/app')
os.environ['DATABASE_URL'] = 'postgresql://root:root123@postgres:5432/tender_scraper'

from app.core.browser import StealthBrowser
from app.database.db import Database

BASE       = "https://www.cqggzy.com"
START_DATE = date(2026, 1, 1)
END_DATE   = date(2026, 5, 31)

CATEGORIES = [
    ("014001019", "招标计划",        "engineering"),
    ("014001001", "招标公告",        "engineering"),
    ("014001003", "中标候选人公示",  "engineering"),
    ("014001004", "中标结果公示",    "engineering"),
    ("014001016", "相关公告",        "engineering"),
    ("014001002", "答疑变更",        "engineering"),   # 工程答疑变更
    ("014001021", "终止公告",        "engineering"),
    ("014005001", "采购公告",        "government"),
    ("014005002", "答疑变更",        "government"),    # 采购答疑变更
    ("014005004", "采购结果公告",    "government"),
]
NO_COLLECT = {"014001014", "014001020", "014001023", "014005008", "014001018"}


def build_url(catnum: str, section: str) -> str:
    prefix = "014005" if section == "government" else "014001"
    return f"{BASE}/xxhz/{prefix}/{catnum}/transaction_detail.html"


def parse_date_from_url(url: str):
    """从 URL path 提取日期，如 /20260527/"""
    m = re.search(r'/(\d{8})/', url)
    if m:
        d = m.group(1)
        try:
            return date(int(d[:4]), int(d[4:6]), int(d[6:8]))
        except ValueError:
            pass
    return None


def make_url_absolute(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return BASE + href
    return BASE + "/" + href


async def extract_rows_from_dom(page) -> List[Dict]:
    """从页面 DOM 提取结果"""
    return await page.evaluate("""
        () => {
            const items = document.querySelectorAll('li.info-item');
            const results = [];
            for (let li of items) {
                const a = li.querySelector('a');
                if (!a) continue;
                const title = (a.innerText || '').trim();
                const href = a.href || '';
                const spans = Array.from(li.querySelectorAll('span'))
                    .map(s => (s.innerText || '').trim());
                results.push({ title, href, spans });
            }
            return results;
        }
    """)


async def get_total(page) -> int:
    text = await page.inner_text('body')
    m = re.search(r'共\s*([\d,]+)\s*条', text)
    if m:
        return int(m.group(1).replace(',', ''))
    return 0


async def click_page_num(page, num: int) -> bool:
    """点击指定页码"""
    try:
        # 直接用 evaluate 点击包含该数字的 pageIdx 链接
        clicked = await page.evaluate(f"""
            () => {{
                const links = document.querySelectorAll('a.pageIdx');
                for (let a of links) {{
                    if (a.textContent.trim() == '{num}') {{
                        a.click();
                        return true;
                    }}
                }}
                return false;
            }}
        """)
        return clicked
    except Exception:
        return False


async def go_next_page(page) -> bool:
    """点击下一页"""
    try:
        # 找到当前页码，然后点下一个
        current = await page.evaluate("""
            () => {
                const current = document.querySelector('span.pageIdx, a.pageIdx.current, span.current');
                if (!current) return 0;
                const text = current.textContent.trim();
                return parseInt(text) || 0;
            }
        """)
        return await click_page_num(page, current + 1)
    except Exception:
        return False


def write_records(records: List[Dict], info_type: str) -> int:
    if not records:
        return 0
    db = Database()
    written = 0
    for rec in records:
        href = make_url_absolute(rec["href"])
        if not href:
            continue

        # 从 URL 提取日期
        date_from_url = parse_date_from_url(href)
        if date_from_url and (date_from_url < START_DATE or date_from_url > END_DATE):
            continue

        # 从 span 提取日期
        pub_date = date_from_url
        date_str = str(date_from_url) if date_from_url else ""
        for span in rec.get("spans", []):
            m = re.match(r'(\d{4}-\d{2}-\d{2})', span)
            if m:
                try:
                    pub_date = datetime.strptime(m.group(1), "%Y-%m-%d").date()
                    date_str = m.group(1)
                    break
                except ValueError:
                    pass

        db.upsert_projects([{
            "url": href,
            "title": rec["title"][:500],
            "info_type": info_type,
            "publish_date": pub_date,
            "publish_date_raw": date_str,
            "region": "",
            "source_url": href,
            "scraped_by": "cqggzy_detail_pw",
            "content_preview": "",
            "full_content": "",
        }])
        written += 1
    return written


async def scrape_category(browser, catnum: str, info_type: str, section: str) -> tuple[int, int]:
    url = build_url(catnum, section)
    print(f"  → {url}")

    page = await browser.new_page()

    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)
    except Exception as e:
        print(f"  ⚠ goto 失败: {e}")
        await page.close()
        return 0, 0

    total_count = await get_total(page)

    # 提取第1页
    rows_p1 = await extract_rows_from_dom(page)
    seen_urls: Set[str] = {r["href"] for r in rows_p1}
    written = write_records(rows_p1, info_type)
    print(f"  第1页: +{written} 条 (网站共 {total_count} 条)")

    # 翻页
    page_num = 2
    max_pages = 500
    while page_num <= max_pages:
        ok = await click_page_num(page, page_num)
        if not ok:
            print(f"  第{page_num}页: 找不到按钮，停止")
            break

        await asyncio.sleep(2.5)

        rows = await extract_rows_from_dom(page)
        if not rows:
            print(f"  第{page_num}页: 无数据，停止")
            break

        # 去重
        new_rows = [r for r in rows if r["href"] not in seen_urls]
        seen_urls.update(r["href"] for r in new_rows)

        w = write_records(new_rows, info_type)
        written += w
        print(f"  第{page_num}页: +{w} new / total {written}")

        page_num += 1

        if page_num > max_pages:
            print(f"  安全限制: {max_pages} 页")
            break

    await page.close()
    return written, total_count


async def main():
    print("╔═══════════════════════════════════════════════════════╗")
    print("║  CQGGZY transaction_detail 全分类采集 (Playwright v2) ║")
    print("╚═══════════════════════════════════════════════════════╝")
    print(f"日期范围: {START_DATE} ~ {END_DATE}\n")

    browser = StealthBrowser(headless=True, slow_mo=5)
    await browser.start()

    grand = 0
    for catnum, info_type, section in CATEGORIES:
        if catnum in NO_COLLECT:
            continue
        print(f"\n▶ {info_type} ({catnum})")
        written, total = await scrape_category(browser, catnum, info_type, section)
        print(f"  → 写入 {written} 条 / 网站 {total} 条")
        grand += written
        await asyncio.sleep(1)

    await browser.close()
    print(f"\n✅ 总计写入: {grand} 条")


if __name__ == "__main__":
    asyncio.run(main())
