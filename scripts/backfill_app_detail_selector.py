#!/usr/bin/env python3
"""
回填脚本：使用 div.app-detail selector 重新采集 projects_cqggzy 中
fc 空 / 短 (< 200) 的记录，COALESCE 保护（仅当新 fc 更长时更新）

用法:
  LIMIT=30 python3 scripts/backfill_app_detail_selector.py      # 30 条测试
  python3 scripts/backfill_app_detail_selector.py               # 全部 (90 天窗口内)
  DAYS=120 python3 scripts/backfill_app_detail_selector.py      # 120 天窗口
  CONCURRENCY=3 python3 scripts/backfill_app_detail_selector.py # 3 并发
"""
import asyncio
import csv
import os
import sys
from datetime import datetime
from typing import List, Dict

import psycopg2

PWD = 'root123'
DAYS = int(os.environ.get('DAYS', 90))  # 90 天窗口
LIMIT = int(os.environ.get('LIMIT', 0))  # 0 = 不限
CONCURRENCY = int(os.environ.get('CONCURRENCY', 5))
MIN_OLD_FC = int(os.environ.get('MIN_OLD_FC', 200))  # 仅回填 fc < 200 的


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def find_candidates(limit: int = 0, days: int = 90) -> List[Dict]:
    """找需要重新采集的记录
    条件: fc 空 或 fc < MIN_OLD_FC
          AND publish_date 在 DAYS 天内 (服务端 90 天窗口)
          AND 不是 招标计划 (c9e57ee 已 skip)
    """
    sql = f"""
        SELECT id, url, title, full_content, content_preview
        FROM projects_cqggzy
        WHERE (full_content IS NULL OR full_content = '' OR LENGTH(full_content) < {MIN_OLD_FC})
          AND publish_date >= CURRENT_DATE - INTERVAL '{days} days'
          AND url NOT LIKE '%/tenderplan/%'
        ORDER BY 
          -- 优先补 6-12 之后 (最近 4 天) 的 — 修复后立即见效
          CASE WHEN publish_date >= '2026-06-12' THEN 0 ELSE 1 END,
          publish_date DESC, id
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
    return [{'id': r[0], 'url': r[1], 'title': r[2], 'old_fc': r[3] or '', 'old_cp': r[4] or ''} for r in rows]


async def fetch_with_app_detail(sem: asyncio.Semaphore, browser, item: Dict) -> Dict:
    """用 div.app-detail selector 抓取详情页"""
    import re
    async with sem:
        result = {
            'id': item['id'],
            'url': item['url'],
            'title': item['title'],
            'old_fc_len': len(item['old_fc']),
            'full_content': '',
            'content_preview': '',
            'status': 'failed',
            'err': '',
        }
        page = None
        try:
            page = await browser.new_page()
            await page.goto(item['url'], wait_until='networkidle', timeout=45000)
            await asyncio.sleep(2)
            # 滚动触发懒加载
            try:
                for _ in range(3):
                    await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    await asyncio.sleep(0.4)
            except Exception:
                pass

            # 2026-06-13 修复: 优先 .app-detail (CQGGZY 详情页官方正文容器)
            el = await page.query_selector('div.app-detail')
            if not el:
                result['err'] = 'no .app-detail'
                return result
            full = await el.inner_text()
            if len(full) < 21:
                result['err'] = f'.app-detail too short ({len(full)})'
                return result

            # clean + strip title dup
            from app.utils.clean_noise import clean_text, make_content_preview
            cleaned = clean_text(full)
            if len(cleaned) < 21:
                result['err'] = f'cleaned too short ({len(cleaned)})'
                return result

            result['full_content'] = cleaned
            result['content_preview'] = make_content_preview(cleaned, item['title'])
            result['status'] = 'ok'
        except Exception as e:
            result['err'] = str(e)[:120]
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
        return result


async def update_batch(batch: List[Dict]):
    """批量 UPDATE: 仅当新 fc > 旧 fc 时更新 (COALESCE 保护)"""
    if not batch:
        return
    from psycopg2.extras import execute_batch
    conn = psycopg2.connect(host='postgres', user='root', password=PWD, dbname='tender_scraper')
    try:
        # COALESCE 保护: 仅当新 fc 更长时覆盖
        # 参数顺序必须匹配 SQL 占位符顺序: cp, new_len, new_fc, id
        rows = []
        for b in batch:
            new_fc = b['full_content']
            new_cp = b['content_preview']
            rows.append((
                new_cp,         # SET content_preview = %s
                len(new_fc),    # WHEN %s > LENGTH(full_content)
                new_fc,         # THEN %s
                b['id'],        # WHERE id = %s
            ))
        execute_batch(
            conn.cursor(),
            """
            UPDATE projects_cqggzy
            SET content_preview = %s,
                full_content = CASE
                    WHEN %s > COALESCE(LENGTH(full_content), 0) THEN %s
                    ELSE full_content
                END
            WHERE id = %s
            """,
            rows,
            page_size=50,
        )
        conn.commit()
    finally:
        conn.close()


async def main():
    candidates = find_candidates(LIMIT, DAYS)
    log(f"📋 待回填: {len(candidates)} 条 (DAYS={DAYS}, MIN_OLD_FC={MIN_OLD_FC}, CONCURRENCY={CONCURRENCY})")
    if not candidates:
        log("✅ 无待回填记录")
        return

    # 备份原值到 TSV
    backup_path = f"/tmp/backfill_app_detail_preserved_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tsv"
    with open(backup_path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['id', 'url', 'old_fc', 'old_cp'], delimiter='\t')
        w.writeheader()
        for c in candidates:
            w.writerow({
                'id': c['id'], 'url': c['url'],
                'old_fc': c['old_fc'][:500],  # 截断避免超长
                'old_cp': c['old_cp'][:500],
            })
    log(f"💾 备份: {backup_path}")

    from playwright.async_api import async_playwright
    browser = None
    success = failed = short_skip = 0
    improved = 0
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            sem = asyncio.Semaphore(CONCURRENCY)
            tasks = [fetch_with_app_detail(sem, browser, item) for item in candidates]
            batch: List[Dict] = []
            total = len(tasks)
            for i, coro in enumerate(asyncio.as_completed(tasks), 1):
                try:
                    r = await coro
                    if r['status'] == 'ok':
                        success += 1
                        new_len = len(r['full_content'])
                        if new_len > r['old_fc_len']:
                            improved += 1
                            batch.append(r)
                        else:
                            short_skip += 1
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1

                if i % 20 == 0 or i == total:
                    log(f"  进度: {i}/{total} (ok={success}, 提升={improved}, 短跳过={short_skip}, 失败={failed})")

                if len(batch) >= 50:
                    await update_batch(batch)
                    batch = []
            if batch:
                await update_batch(batch)
    finally:
        if browser:
            await browser.close()

    log(f"\n✅ 完成: ok={success}, 提升={improved}, 短跳过={short_skip}, 失败={failed}")
    log(f"💾 备份文件: {backup_path}")


if __name__ == "__main__":
    asyncio.run(main())
