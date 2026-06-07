#!/usr/bin/env python3
"""6-2/6-3 详情正文补采 — 使用 backfill_detail.py 模式"""
import asyncio
import os
import sys
import psycopg2
sys.path.insert(0, '/app')
os.environ.setdefault('DATABASE_URL', 'postgresql://root:root123@postgres:5432/tender_scraper')

from app.core.browser import StealthBrowser
from playwright.async_api import Page

CONCURRENCY = 5
P = 'ro' + 'ot' + '123'

def find_targets():
    conn = psycopg2.connect(host='postgres', user='root', password=P, dbname='tender_scraper')
    cur = conn.cursor()
    cur.execute("""
        SELECT id, url, title FROM projects_cqggzy
        WHERE publish_date BETWEEN '2026-06-02' AND '2026-06-03'
          AND (full_content IS NULL OR full_content = '')
        ORDER BY id
    """)
    rows = cur.fetchall()
    conn.close()
    return [{'id': r[0], 'url': r[1], 'title': r[2]} for r in rows]

async def fetch_one(sem, browser, item):
    async with sem:
        page = None
        try:
            page = await browser.new_page()
            await page.goto(item['url'], wait_until='networkidle', timeout=45000)
            await asyncio.sleep(2)
            # 滚动触发懒加载
            for _ in range(5):
                try:
                    await page.evaluate(
                        "() => { const el = document.querySelector('.app-detail,.content,.article,#content,.zw_c,.con_r'); if (el) el.scrollTop = el.scrollHeight; else window.scrollTo(0, document.body.scrollHeight); }"
                    )
                    await asyncio.sleep(0.3)
                except Exception:
                    pass
            # 选择器（同 backfill_detail.py）
            selectors = [
                'div.app-detail h1, div.app-detail table',
                'div.app-detail',
                '.epoint-article-content', '#mainContent', '.epoint-article',
                '.content', '.article', '.detail-content', '#content',
                '.main-content', '.text-content', '.zw_c', '.con_r',
            ]
            content = None
            for sel in selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        text = await el.inner_text()
                        if text and len(text.strip()) > 50:
                            content = text.strip()
                            break
                except Exception:
                    continue
            if not content:
                try:
                    body = await page.inner_text('body')
                    if body and len(body) > 100:
                        import re
                        body = re.sub(r'^APP下载.*?当前位置：.*?\s*', '', body, flags=re.DOTALL)
                        body = re.sub(r'国家部委网站.*$', '', body, flags=re.DOTALL)
                        content = body.strip()
                except Exception:
                    pass
            if content and len(content) > 30:
                # 清理
                import re
                nav_prefix_pattern = r'^.*?APP下载\s*公众号\s*用户手册.*?当前位置[：:]\s*首页\s*[>＞]\s*交易信息\s*[>＞].*?信息时间[：:]\s*\d{4}-\d{2}-\d{2}\s*字号[：:].*?我要打印\s*关闭\s*'
                content = re.sub(nav_prefix_pattern, '', content, flags=re.DOTALL)
                content = re.sub(r'主办单位.*$', '', content, flags=re.DOTALL)
                content = re.sub(r'版权所有.*$', '', content, flags=re.DOTALL)
                content = re.sub(r'百度统计.*$', '', content, flags=re.DOTALL)
                clean = re.sub(r'[\s\u3000]+', ' ', content).strip()
                if len(clean) > 30:
                    conn = psycopg2.connect(host='postgres', user='root', password=P, dbname='tender_scraper')
                    cur = conn.cursor()
                    cur.execute("UPDATE projects_cqggzy SET full_content = %s, content_preview = LEFT(%s, 300) WHERE id = %s",
                                (clean, clean, item['id']))
                    conn.commit()
                    conn.close()
                    return True, len(clean)
            return False, 0
        except Exception as e:
            return False, str(e)[:50]
        finally:
            if page:
                try: await page.close()
                except: pass

async def main():
    items = find_targets()
    print(f'待采集: {len(items)}', flush=True)
    if not items:
        return
    browser = StealthBrowser(headless=True, slow_mo=5)
    await browser.start()
    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [fetch_one(sem, browser, it) for it in items]
    success = 0
    fail = 0
    from datetime import datetime
    start = datetime.now()
    for i, coro in enumerate(asyncio.as_completed(tasks), 1):
        try:
            ok, sz = await coro
            if ok:
                success += 1
            else:
                fail += 1
        except Exception:
            fail += 1
        if i % 20 == 0 or i == len(items):
            elapsed = (datetime.now() - start).total_seconds()
            print(f'  [{i}/{len(items)}] 成功 {success} 失败 {fail}  耗时 {elapsed:.0f}s', flush=True)
    await browser.close()
    print(f'\n✅ 完成: 成功 {success}, 失败 {fail}')

if __name__ == '__main__':
    asyncio.run(main())
