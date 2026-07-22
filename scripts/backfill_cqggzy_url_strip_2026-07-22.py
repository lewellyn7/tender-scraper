#!/usr/bin/env python3
"""
CQGGZY URL 后缀扩大修复 - 2026-07-22
==========================
- 痛点: PR #87 (e1a484c) 加了 014005004 守卫, 但 collector 容器没 rebuild
  (镜像构建于 2026-07-15, PR #87 是 2026-07-21), 仍跑旧代码 (无条件 _1).
  结果 7 类白名单 (除 014005004 外) 全部错版 _1 URL 写入 DB (~25578 条).
- 修复: 剥掉非 '采购结果公告' 类目 URL 中的 _N 后缀, 重抓详情回填 cp/fc.
- 范围: category != '采购结果公告' AND url ~ r'/\d+_\d+(\?|$)'
  含 (PR #87 当时未处理的剩余 ~25578 条):
    - 采购公告 (014005001): 15643 条
    - 变更公告 (014005002): 7403 条
    - 政府采购 (杂): 179 条
    - 空 category (按 URL 中 categoryNum 判定): 2353 条

用法:
  docker exec tender-scraper-web python /app/scripts/backfill_cqggzy_url_strip_2026-07-22.py
  LIMIT=20 python ...        # 限制条数 (测试用)
  SKIP_STRIP=1 python ...    # 只重抓不剥 (URL 已是正确裸 ID 的情况)
  DRY_RUN=1 python ...       # 只看不动
"""
import asyncio
import os
import re
import sys
from typing import List, Dict, Optional

import psycopg2

sys.path.insert(0, '/app')
os.environ.setdefault('DATABASE_URL', 'postgresql://root:root123@postgres:5432/tender_scraper')

from app.core.browser import StealthBrowser

PWD = 'root123'
LIMIT = int(os.environ.get('LIMIT', 0))  # 0 = 全部
CONCURRENCY = int(os.environ.get('CONCURRENCY', 8))
DRY_RUN = os.environ.get('DRY_RUN', '0') == '1'
SKIP_STRIP = os.environ.get('SKIP_STRIP', '0') == '1'

# URL 中 infoid 段: /<digits>_<digits>?  → 剥成 /<digits>?
_UNDERSCORE_RE = re.compile(r'(/(\d+))_\d+(\?|$)')

# 保留 _N 的类目 (category 列存的是中文 info_type, 不是 catnum)
KEEP_UNDERSCORE_CATEGORIES = {'采购结果公告'}  # = 014005004


def log(msg):
    print(f"[{__import__('datetime').datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _conn():
    return psycopg2.connect(host='postgres', user='root', password=PWD, dbname='tender_scraper')


def _strip_url(url: str) -> str:
    """剥掉 /<digits>_<digits> 里的 _N, 保留前段数字 + query"""
    return _UNDERSCORE_RE.sub(r'\1\3', url)


def find_candidates(limit: int = 0) -> List[Dict]:
    """找需重抓记录: 本次 bug 真正受害者 (7-22 限定数字 infoid 格式)

    范围:
    - url NOT LIKE '%categoryNum=014005004%'  (采购结果公告不需重抓)
    - url ~ r'/\d+\?'  (数字 infoid 格式, 不是 UUID / HTML 路径)
    - url NOT LIKE '%/\d+_\d+%' (已剥 _1, 避免重跳 PR #87 的坑)
    - cp/fc 为空 (含占位符 '渝公网安备 50019002503055 号')

    7-22 调研后限定: 实测 LIMIT=10 含 UUID/HTML 路径样本, selector 抓不到,
    这些历史不成功的项目不在本次 bug 修复范围. 数字 infoid 是本次 bug 受害者.
    """
    sql = """
        SELECT id, url, title, category
        FROM projects_cqggzy
        WHERE (content_preview IS NULL OR content_preview = ''
               OR full_content IS NULL OR full_content = ''
               OR full_content = '渝公网安备 50019002503055 号')
          AND url NOT LIKE '%categoryNum=014005004%'
          AND url ~ '/\\d+\\?'
          AND url !~ '/\\d+_\\d+(\\?|$)'
        ORDER BY publish_date DESC NULLS LAST, id DESC
    """
    if limit:
        sql += f" LIMIT {limit}"
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
    finally:
        conn.close()
    return [{'id': r[0], 'url': r[1], 'title': r[2], 'category': r[3]} for r in rows]


def strip_urls_in_db() -> int:
    """SQL 级批量剥 _1 (不等抓详情, 先把 URL 修正)

    判断规则: 看 URL 里的 categoryNum (不是 DB 的 category 列).
    - categoryNum=014005004 (采购结果公告): 保留 _N (API 真实返 _N)
    - 其他: 剥 _N (API 只返裸数字)

    注意: 调之前必须先调 strip_duplicate_urls_in_db() 删冲突行.
    """
    if SKIP_STRIP or DRY_RUN:
        return 0
    sql = """
        UPDATE projects_cqggzy
        SET url = REGEXP_REPLACE(url, '/(\\d+)_\\d+(\\?|$)', '/\\1\\2')
        WHERE url ~ '/\\d+_\\d+(\\?|$)'
          AND url NOT LIKE '%categoryNum=014005004%'
    """
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        affected = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return affected


def strip_duplicate_urls_in_db() -> int:
    """DELETE 错版 _1 行 (剥 _1 后会撞裸 ID UNIQUE).

    场景: PR #87 backfill 已 UPDATE 406 条 URL 剥 _1, 现在还剩 20000+ 条 _1
    待剥. 剥其中一些时会撞已存在的裸 ID URL → UNIQUE violation.
    解决: 先 DELETE 这些会冲突的错版行 (重复数据).
    """
    if SKIP_STRIP or DRY_RUN:
        return 0
    sql = """
        DELETE FROM projects_cqggzy p
        WHERE url ~ '/\\d+_\\d+(\\?|$)'
          AND url NOT LIKE '%categoryNum=014005004%'
          AND EXISTS (
              SELECT 1 FROM projects_cqggzy e
              WHERE e.url = REGEXP_REPLACE(p.url, '/(\\d+)_\\d+(\\?|$)', '/\\1\\2')
                AND e.id != p.id
          )
    """
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        affected = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return affected


async def fetch_one(browser, item: Dict, retry: int = 2) -> Dict:
    """采集单条详情 (含 retry)

    7-22 改进: 
    - 加 retry=2 (默认重试 2 次, 首次 + 2 重试 = 3 次机会)
    - 实时打 fail 详情 (含 err + url + id)
    - 使用 domcontentloaded (更快, 不等 networkidle)
    """
    result = {
        'id': item['id'],
        'url': item['url'],
        'title': item['title'],
        'category': item.get('category', ''),
        'content_preview': '',
        'full_content': '',
        'status': 'failed',
        'error': '',
        'attempts': 0,
    }
    last_err = ''
    for attempt in range(retry + 1):
        result['attempts'] = attempt + 1
        page = None
        try:
            page = await browser.new_page()
            await page.goto(item['url'], wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(1.0)

            # 滚动触发懒加载
            try:
                for _ in range(2):
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

            # 抓 H1 块
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
                full = re.sub(r'^.*?当前位置[：:].*?关闭\s*', '', full, flags=re.DOTALL)
                if len(full) > 30:
                    result['content_preview'] = full[:300]
                    result['full_content'] = full
                    result['status'] = 'ok'
                    result['error'] = ''
                    return result
            last_err = 'no_content_matched'
        except Exception as e:
            last_err = f'{type(e).__name__}: {str(e)[:80]}'
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
        # retry 前 sleep (递增退避)
        if attempt < retry:
            await asyncio.sleep(1.5 * (attempt + 1))

    result['error'] = last_err
    return result


async def update_one(item: Dict):
    """更新 DB 一条 (cp + fc)"""
    if DRY_RUN:
        return
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE projects_cqggzy
               SET content_preview = %s, full_content = %s, updated_at = NOW()
               WHERE id = %s""",
            (item['content_preview'], item['full_content'], item['id'])
        )
        conn.commit()
    finally:
        conn.close()


async def main():
    log("=" * 60)
    log("CQGGZY URL 后缀扩大修复 - 2026-07-22")
    log(f"参数: LIMIT={LIMIT}, CONCURRENCY={CONCURRENCY}, DRY_RUN={DRY_RUN}, SKIP_STRIP={SKIP_STRIP}")
    log("=" * 60)

    # Step 1: SQL 级批量剥 _1
    if not SKIP_STRIP:
        if DRY_RUN:
            log("[DRY_RUN] 跳过 URL 剥 _1 (只统计候选)")
            n_strip = 0
        else:
            log("🔧 Step 1a: SQL DELETE 重复 (剥 _1 后撞裸 ID UNIQUE) ...")
            n_del = strip_duplicate_urls_in_db()
            log(f"   ✓ 删 {n_del} 条重复错版 (剥 _1 后与裸 ID 冲突)")
            log("🔧 Step 1b: SQL UPDATE 剥 _1 → 裸 ID ...")
            n_strip = strip_urls_in_db()
            log(f"   ✓ 剥 {n_strip} 条 URL 中的 _N 后缀")
    else:
        log("⏭️  Step 1: SKIP_STRIP=1, 跳过 SQL 剥 _1")
        n_strip = 0

    # Step 2: 找剩余需重抓的 (cp/fc 空) - 用剥后 URL
    log("🔍 Step 2: 找需重抓的记录 (cp/fc 空) ...")
    candidates = find_candidates(LIMIT)
    log(f"   找到 {len(candidates)} 条待重抓")

    if not candidates:
        log("✅ 无需重抓")
        return

    if DRY_RUN:
        log(f"[DRY_RUN] 前 5 条样本:")
        for c in candidates[:5]:
            log(f"   id={c['id']} cat={c['category']} url={c['url'][:80]}...")
        return

    browser = None
    try:
        browser = StealthBrowser(headless=True, slow_mo=0)
        await browser.start()
        sem = asyncio.Semaphore(CONCURRENCY)
        ok = 0
        fail = 0
        fail_samples: List[Dict] = []
        consecutive_fail = 0  # 连续失败计数 (防反爬退避)

        async def task(item):
            nonlocal ok, fail, consecutive_fail
            async with sem:
                res = await fetch_one(browser, item, retry=2)
                if res['status'] == 'ok':
                    await update_one(res)
                    ok += 1
                    consecutive_fail = 0
                else:
                    fail += 1
                    consecutive_fail += 1
                    if len(fail_samples) < 20:
                        fail_samples.append(res)
                    # 实时打 fail (含 err 详情)
                    log(f"   ✗ id={res['id']} cat={res['category'][:8]} err={res['error'][:60]} url={res['url'][-50:]}")
                total = ok + fail
                if total % 50 == 0 or total == len(candidates):
                    rate = ok * 100 // max(total, 1)
                    log(f"   进度: {total}/{len(candidates)} (ok={ok}, fail={fail}, 成功率={rate}%)")
                # 防反爬: 连续失败 >= 10, sleep 5s
                if consecutive_fail >= 10:
                    log(f"   ⚠️  连续失败 {consecutive_fail}, sleep 5s 防反爬")
                    await asyncio.sleep(5)
                    consecutive_fail = 0

        tasks = [task(c) for c in candidates]
        await asyncio.gather(*tasks, return_exceptions=True)
        log(f"🏁 重抓完成: ok={ok}, fail={fail}, total={len(candidates)}, 成功率={ok*100//max(ok+fail,1)}%")
        if fail_samples:
            log(f"⚠️ 失败样本 (前 {len(fail_samples)}):")
            for f in fail_samples:
                log(f"   id={f['id']} attempts={f.get('attempts', '?')} err={f['error'][:80]}")
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass


if __name__ == '__main__':
    asyncio.run(main())