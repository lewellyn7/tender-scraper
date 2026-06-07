#!/usr/bin/env python3
"""
详情页批量回采脚本
- 从 DB 找 content_preview 为空/无内容/=title 或 full_content 为空的记录
- 重新访问详情页
- 提取 content_preview + full_content
- UPDATE DB

用法:
  python3 scripts/backfill_detail.py                    # 全部
  LIMIT=100 python3 scripts/backfill_detail.py          # 限制 100 条
  CONCURRENCY=5 python3 scripts/backfill_detail.py     # 5 并发
"""
import asyncio
import os
import re
import sys
from typing import List, Dict

import psycopg2
PWD = 'root123'

sys.path.insert(0, '/app')
os.environ.setdefault('DATABASE_URL', 'postgresql://root:root123@postgres:5432/tender_scraper')

from app.core.browser import StealthBrowser
from app.crawlers.cqggzy import CQGGZYCrawlerV2
# Database 类跳过（asyncpg 兼容问题）
from playwright.async_api import Page

LIMIT = int(os.environ.get('LIMIT', 0))  # 0 = 不限
CONCURRENCY = int(os.environ.get('CONCURRENCY', 5))  # 并发数
BATCH_UPDATE_SIZE = 50  # 每 50 条 commit


def log(msg):
    print(f"[{__import__('datetime').datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def find_candidates(limit: int = 0) -> List[Dict]:
    """找需要重新采集的记录（用 raw psycopg2）"""
    sql = """
        SELECT id, url, title
        FROM projects_cqggzy
        WHERE full_content IS NULL OR full_content = ''
           OR content_preview IS NULL OR content_preview = ''
           OR content_preview = title
           OR content_preview = '无内容'
           -- 过滤"导航文本"：content_preview 以 "APP下载" 开头但 full_content 不为空
           OR (content_preview LIKE 'APP下载%' AND LENGTH(full_content) > 100)
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


async def fetch_one_detail(sem: asyncio.Semaphore, browser, item: Dict) -> Dict:
    """单条详情页采集"""
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
            await page.goto(item['url'], wait_until='networkidle', timeout=45000)
            await asyncio.sleep(2)
            
            # 滚动触发懒加载
            try:
                for _ in range(5):
                    await page.evaluate(
                        "() => { const el = document.querySelector('.app-detail,.content,.article,#content,.zw_c,.con_r'); if (el) el.scrollTop = el.scrollHeight; else window.scrollTo(0, document.body.scrollHeight); }"
                    )
                    await asyncio.sleep(0.3)
            except Exception:
                pass
            
            # CQGGZY 详情页正文在 .app-detail（HTML 表格包裹）
            # 优先级最高：app-detail 内的 h1 (项目标题) 或 table (项目表格)
            selectors = [
                'div.app-detail h1, div.app-detail table',  # 最精准：标题/表格
                'div.app-detail',         # CQGGZY 实际正文容器
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
            
            # 备用：body 过滤掉导航
            if not content:
                try:
                    body = await page.inner_text('body')
                    # 过滤导航噪音
                    if body and len(body) > 100:
                        # 去掉常见导航/页脚
                        nav_patterns = [
                            r'APP下载\s*公众号.*?搜索',
                            r'人民法院诉讼资产网\s*\|\s*交易监督网.*?加入收藏',
                            r'首页\s*资讯动态.*?保证金退还信息',
                            r'政策法规\s*法律.*?综合法规',
                        ]
                        clean = body
                        for pat in nav_patterns:
                            import re as _r
                            clean = _r.sub('', clean, flags=_r.DOTALL)
                        clean = re.sub(r'\s+', ' ', clean).strip()
                        if len(clean) > 30:
                            content = clean
                except Exception:
                    pass
            
            if content:
                # 清理
                import re as re_module
                # 强力去掉导航噪音前缀（面包屑）
                nav_prefix_pattern = r'^.*?APP下载\s*公众号\s*用户手册.*?当前位置[：:]\s*首页\s*[>＞]\s*交易信息\s*[>＞].*?信息时间[：:]\s*\d{4}-\d{2}-\d{2}\s*字号[：:].*?我要打印\s*关闭\s*'
                content = re_module.sub(nav_prefix_pattern, '', content, flags=re_module.DOTALL)
                nav_prefix_pattern2 = r'^.*?人民法院诉讼资产网.*?当前位置[：:].*?信息时间[：:].*?我要打印\s*关闭\s*'
                content = re_module.sub(nav_prefix_pattern2, '', content, flags=re_module.DOTALL)
                # 去掉页脚
                content = re_module.sub(r'主办单位.*$', '', content, flags=re_module.DOTALL)
                content = re_module.sub(r'版权所有.*$', '', content, flags=re_module.DOTALL)
                content = re_module.sub(r'百度统计.*$', '', content, flags=re_module.DOTALL)
                # 标准化空白
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


async def main():
    candidates = find_candidates(LIMIT)
    log(f"📋 待采集: {len(candidates)} 条 (并发={CONCURRENCY})")
    
    if not candidates:
        log("✅ 无待采集记录")
        return
    
    browser = None
    try:
        browser = StealthBrowser(headless=True, slow_mo=0)
        await browser.start()

        sem = asyncio.Semaphore(CONCURRENCY)
        tasks = [fetch_one_detail(sem, browser, item) for item in candidates]
        
        success = 0
        failed = 0
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
            
            # 进度
            if i % 10 == 0 or i == total:
                log(f"  进度: {i}/{total} (成功 {success}, 失败 {failed})")
            
            # 批量更新
            if len(batch) >= BATCH_UPDATE_SIZE:
                await update_batch(None, batch)
                batch = []

        # 剩余
        if batch:
            await update_batch(None, batch)
        
        log(f"\n✅ 完成: 成功 {success}, 失败 {failed}")
    finally:
        if browser:
            await browser.close()


async def update_batch(db, batch):
    """批量 UPDATE content_preview + full_content"""
    if not batch:
        return
    try:
        from psycopg2.extras import execute_batch
        # 用 raw psycopg2 连接（避免 Database 单例 asyncpg 兼容问题）
        raw_conn = psycopg2.connect(host='postgres', user='root', password=PWD, dbname='tender_scraper')
        try:
            rows = [(b['content_preview'], b['full_content'], b['id']) for b in batch]
            execute_batch(
                raw_conn.cursor(),
                "UPDATE projects_cqggzy SET content_preview = %s, full_content = %s WHERE id = %s",
                rows,
                page_size=50,
            )
            raw_conn.commit()
            log(f"  📦 批量更新 {len(batch)} 条")
        finally:
            raw_conn.close()
    except Exception as e:
        log(f"  ❌ 批量更新失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())
