#!/usr/bin/env python3
"""
CQGGZY URL 后缀修复 - 详情重抓脚本
2026-07-21 修复: 采购公告/变更公告 014005001/002 错误加 _1 后缀 → 剥掉后重抓详情

用法:
  docker exec tender-scraper-web python /app/scripts/backfill_cqggzy_url_suffix_2026-07-21.py
  LIMIT=50 python ...   # 限制条数（测试用）
"""
import asyncio
import os
import re
import sys
from typing import List, Dict

import psycopg2

sys.path.insert(0, '/app')
os.environ.setdefault('DATABASE_URL', 'postgresql://root:root123@postgres:5432/tender_scraper')

from app.core.browser import StealthBrowser

PWD = 'root123'
LIMIT = int(os.environ.get('LIMIT', 0))  # 0 = 全部 406 条
CONCURRENCY = int(os.environ.get('CONCURRENCY', 8))
DRY_RUN = os.environ.get('DRY_RUN', '0') == '1'


def log(msg):
    print(f"[{__import__('datetime').datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def find_candidates(limit: int = 0) -> List[Dict]:
    """找需要重新采集的记录：014005001/002 + URL 已剥 _1 + cp 仍空"""
    sql = """
        SELECT id, url, title
        FROM projects_cqggzy
        WHERE url ~ '/014005/\\d+\\?categoryNum=01400500[12]'
          AND (content_preview IS NULL OR content_preview = '')
          AND (full_content IS NULL OR full_content = ''
               OR full_content = '渝公网安备 50019002503055 号')
        ORDER BY publish_date DESC
    """
    if limit:
        sql += f" LIMIT {limit}"
    conn = psycopg2.connect(host='postgres', user='root', password=PWD, dbname='tender_scraper')
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
    finally:
        conn.close()
    return [{'id': r[0], 'url': r[1], 'title': r[2]} for r in rows]


async def fetch_one(browser, item: Dict) -> Dict:
    """采集单条详情"""
    result = {
        'id': item['id'],
        'url': item['url'],
        'title': item['title'],
        'content_preview': '',
        'full_content': '',
        'status': 'failed',
        'error': '',
    }
    page = None
    try:
        page = await browser.new_page()
        await page.goto(item['url'], wait_until='networkidle', timeout=45000)
        await asyncio.sleep(1.5)

        # 滚动触发懒加载
        try:
            for _ in range(3):
                await page.evaluate(
                    "() => { const el = document.querySelector('.app-detail,.content,.article,#content'); if (el) el.scrollTop = el.scrollHeight; else window.scrollTo(0, document.body.scrollHeight); }"
                )
                await asyncio.sleep(0.3)
        except Exception:
            pass

        # CQGGZY 详情页正文选择器（与现有 cqggzy.py 一致）
        selectors = [
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

        # 抓 H1 块（项目编号常在 h1 里）
        h1_block = ''
        try:
            h1_texts = await page.eval_on_selector_all(
                'h1',
                'els => els.map(e => e.innerText.trim()).filter(t => t.length > 0)'
            )
            if h1_texts:
                h1_block = '\n'.join(h1_texts)
        except Exception:
            pass

        if content:
            full = (h1_block + '\n' + content).strip() if h1_block else content
            full = re.sub(r'[\s\u3000]+', ' ', full).strip()
            # 去导航前缀
            full = re.sub(r'^.*?当前位置[：:].*?关闭\s*', '', full, flags=re.DOTALL)
            if len(full) > 30:
                result['content_preview'] = full[:300]
                result['full_content'] = full
                result['status'] = 'ok'
    except Exception as e:
        result['error'] = str(e)[:100]
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass
    return result


async def update_one(item: Dict):
    """更新 DB 一条"""
    if DRY_RUN:
        return
    conn = psycopg2.connect(host='postgres', user='root', password=PWD, dbname='tender_scraper')
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE projects_cqggzy
               SET content_preview = %s, full_content = %s
               WHERE id = %s""",
            (item['content_preview'], item['full_content'], item['id'])
        )
        conn.commit()
    finally:
        conn.close()


async def main():
    candidates = find_candidates(LIMIT)
    log(f"📋 待采集: {len(candidates)} 条 (并发={CONCURRENCY}, dry_run={DRY_RUN})")

    if not candidates:
        log("✅ 无待采集记录")
        return

    browser = None
    try:
        browser = StealthBrowser(headless=True, slow_mo=0)
        await browser.start()
        sem = asyncio.Semaphore(CONCURRENCY)
        ok = 0
        fail = 0

        async def task(item):
            nonlocal ok, fail
            async with sem:
                res = await fetch_one(browser, item)
                if res['status'] == 'ok':
                    await update_one(res)
                    ok += 1
                else:
                    fail += 1
                    if res.get('error'):
                        log(f"   ⚠️ fail id={res['id']}: {res['error'][:80]}")
                # 进度日志
                total = ok + fail
                if total % 20 == 0 or total == len(candidates):
                    log(f"   进度: {total}/{len(candidates)} (ok={ok}, fail={fail})")

        tasks = [task(c) for c in candidates]
        await asyncio.gather(*tasks, return_exceptions=True)
        log(f"🏁 完成: ok={ok}, fail={fail}, total={len(candidates)}")
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass


if __name__ == '__main__':
    asyncio.run(main())