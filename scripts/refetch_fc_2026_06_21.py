#!/usr/bin/env python3
"""
近 30 天短 fc 补采脚本（2026-06-21 启动任务专用）

目标: 近 30 天 scraped_at 但 full_content < 200 字节的记录
特点: 
  - 不覆盖已填好的 fc（UPDATE 限定 LENGTH(full_content) < 200）
  - 仅 170 条候选（远小于 91601 全表）
  - 复用 backfill_detail.py 的 fetch_one_detail 逻辑

用法: python3 scripts/refetch_fc_2026_06_21.py

回滚: 从 _fc_backup_2026_06_21 恢复
  UPDATE projects_cqggzy p
  SET full_content = b.full_content
  FROM _fc_backup_2026_06_21 b
  WHERE p.id = b.id;
"""
import asyncio
import os
import sys
import psycopg2
from psycopg2.extras import execute_batch
from datetime import datetime

sys.path.insert(0, '/app')
os.environ.setdefault('DATABASE_URL', 'postgresql://root:root123@postgres:5432/tender_scraper')

from app.core.browser import StealthBrowser
from app.crawlers.cqggzy import CQGGZYCrawlerV2

PWD = 'root123'
CONCURRENCY = int(os.environ.get('CONCURRENCY', 5))
BATCH_UPDATE_SIZE = 30


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def find_candidates() -> list:
    """近 30 天 scrape 但 fc < 200 字节"""
    sql = """
        SELECT id, url, title
        FROM projects_cqggzy
        WHERE (full_content IS NULL OR LENGTH(full_content) < 200)
          AND scraped_at >= NOW() - INTERVAL '30 days'
        ORDER BY scraped_at DESC
    """
    conn = psycopg2.connect(host='postgres', user='root', password=PWD, dbname='tender_scraper')
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
    finally:
        conn.close()
    return [{'id': r[0], 'url': r[1], 'title': r[2]} for r in rows]


async def fetch_one_detail(sem: asyncio.Semaphore, browser, item: dict) -> dict:
    """单条详情采集 - 简化版（直接 inner_text）"""
    async with sem:
        result = {
            'id': item['id'],
            'url': item['url'],
            'title': item['title'],
            'content_preview': '',
            'full_content': '',
            'status': 'failed',
        }
        page = None
        try:
            page = await browser.new_page()
            await page.goto(item['url'], wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(1.5)

            # 滚动触发懒加载
            try:
                await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(0.5)
            except Exception:
                pass

            # 优先 .app-detail
            selectors = [
                'div.app-detail',
                '.epoint-article-content', '#mainContent', '.epoint-article',
                '.content', '.article', '.detail-content', '#content',
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

            if content:
                import re as re_module
                # 去导航噪音前缀
                content = re_module.sub(r'^.*?当前位置[：:].*?我要打印\s*关闭\s*', '', content, flags=re_module.DOTALL)
                content = re_module.sub(r'主办单位.*$', '', content, flags=re_module.DOTALL)
                content = re_module.sub(r'版权所有.*$', '', content, flags=re_module.DOTALL)
                content = re_module.sub(r'百度统计.*$', '', content, flags=re_module.DOTALL)
                clean = re_module.sub(r'[\s\u3000]+', ' ', content).strip()
                if len(clean) > 30:
                    result['content_preview'] = clean[:300]
                    result['full_content'] = clean
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


async def update_batch_safe(batch: list):
    """安全批量更新 — 只覆盖 fc 短/空的（不破坏已有数据）"""
    if not batch:
        return
    try:
        conn = psycopg2.connect(host='postgres', user='root', password=PWD, dbname='tender_scraper')
        try:
            rows = [(b['content_preview'], b['full_content'], b['id']) for b in batch]
            with conn.cursor() as cur:
                execute_batch(
                    cur,
                    """UPDATE projects_cqggzy 
                       SET content_preview = %s, full_content = %s, scraped_at = NOW()
                       WHERE id = %s 
                         AND (full_content IS NULL OR LENGTH(full_content) < 200)""",
                    rows,
                    page_size=30,
                )
            conn.commit()
            log(f"  📦 批量更新 {len(batch)} 条")
        finally:
            conn.close()
    except Exception as e:
        log(f"  ❌ 批量更新失败: {e}")


async def main():
    candidates = find_candidates()
    log(f"📋 待补采: {len(candidates)} 条 (并发={CONCURRENCY})")

    if not candidates:
        log("✅ 无待补采记录")
        return

    browser = None
    try:
        browser = StealthBrowser(headless=True, slow_mo=0)
        await browser.start()

        sem = asyncio.Semaphore(CONCURRENCY)
        tasks = [fetch_one_detail(sem, browser, item) for item in candidates]

        success = 0
        failed = 0
        skipped = 0
        batch = []
        total = len(tasks)

        for i, coro in enumerate(asyncio.as_completed(tasks), 1):
            try:
                result = await coro
                if result['status'] == 'ok':
                    success += 1
                    batch.append(result)
                else:
                    failed += 1
            except Exception as e:
                failed += 1

            if i % 20 == 0 or i == total:
                log(f"  进度: {i}/{total} (成功 {success}, 失败 {failed})")

            if len(batch) >= BATCH_UPDATE_SIZE:
                await update_batch_safe(batch)
                batch = []

        if batch:
            await update_batch_safe(batch)

        log(f"\n✅ 完成: 成功 {success}, 失败 {failed}, 总 {total}")
    finally:
        if browser:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())