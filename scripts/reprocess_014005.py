"""2026-06-08 Bug 1-A 验证: 一次性重处理 6-8 014005 数字 ID 详情页

使用: collector 跑过 list 但 014005 数字 ID URL 之前被 _parse_detail_url
拒绝 (无法解析 UUID). 修复后, 把这些 URL 重新入队跑 detail.

行为:
1. SELECT projects_cqggzy WHERE publish_date = 2026-06-08
   AND url ~ '/trade/014005/[0-9]{16}'
   AND length(content_preview) = 0  (尚未处理)
2. 构造 CrawlTask (priority = 1.0, 最高)
3. 调 SmartScheduler.schedule() 跑 detail
4. 验证 content_preview 被填充
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# 容器内运行: hardcode /app (脚本放在 /app/ 下)
sys.path.insert(0, '/app')
# 脚本路径 /app/reprocess_014005.py, parents[0] = /app, parents[1] = /
# 不要加 / 到 sys.path (会污染 import)
print('DEBUG sys.path[:5]:', sys.path[:5])

from sqlalchemy import create_engine, text
from app.config.settings import settings
from app.core.harvest.smart_scheduler import SmartScheduler, CrawlTask
from app.crawlers.cqggzy import CQGGZYCrawlerV2
from app.crawlers.ccgp import CCGPCrawlerV3
from app.models.tender import TenderInfo
from app.database.db import DATABASE_URL


async def main():
    engine = create_engine(DATABASE_URL)

    # 1. 拉所有未处理的 6-8 014005 数字 ID
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, url, title, publish_date
            FROM projects_cqggzy
            WHERE publish_date = '2026-06-08'
              AND url ~ '/trade/014005/[0-9]{16}'
              AND (content_preview IS NULL OR length(content_preview) = 0)
            ORDER BY id
        """)).fetchall()

    print(f"📥 找到 {len(rows)} 条待处理 014005 数字 ID URL")
    if not rows:
        return

    # 2. 实例化 crawler + scheduler
    from app.core.browser import StealthBrowser
    browser = StealthBrowser(headless=True)
    await browser.start()
    cqggzy_crawler = CQGGZYCrawlerV2(browser=browser)
    ccgp_crawler = CCGPCrawlerV3(browser=browser)
    sched = SmartScheduler(max_concurrent=3)

    async def crawler_fn(task: CrawlTask):
        """根据 task.source 选择正确的 crawler"""
        if task.source == "ccgp":
            return await ccgp_crawler.fetch_detail(task.url)
        # 修复后 014005 数字 ID URL 能正常解析
        tender = TenderInfo(
            url=task.url,
            title="",
            publish_date=task.publish_date,
            source_url="",
        )
        return await cqggzy_crawler.fetch_detail(tender)

    # 3. 构造 CrawlTask 列表
    tasks = []
    for r in rows:
        url = r[1]
        publish_date = r[3]
        if isinstance(publish_date, datetime):
            pd = publish_date
        else:
            pd = datetime.combine(publish_date, datetime.min.time())
        tasks.append(CrawlTask(
            task_id=f"reprocess_{r[0]}",
            url=url,
            source="cqggzy",
            info_type="招标公告",
            publish_date=pd,
            priority_static=10,
            priority_dynamic=1.0,  # 最高
            created_at=datetime.now(),
        ))

    await sched.register_batch(tasks)

    # 4. 调度
    print(f"⏳ 调度 {len(tasks)} 个 task (max_concurrent=3, timeout=600s)...")
    results = await sched.schedule(crawler_fn)

    # 5. 验证 + 写回 DB
    print(f"✅ 调度结果: succeeded={results.get('succeeded',0)} "
          f"failed={results.get('failed',0)} skipped={results.get('skipped',0)}")

    # 6. 写回 DB: 读取 id 列表 + 调 update_full_content
    from app.database.db import get_db
    db = get_db()
    written = 0
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, url FROM projects_cqggzy
            WHERE publish_date = '2026-06-08'
              AND url ~ '/trade/014005/[0-9]{16}'
              AND (content_preview IS NULL OR length(content_preview) = 0)
        """)).fetchall()
        for r in rows:
            row_id, url = r
            # 重抓详情获取最新 content
            tender = TenderInfo(url=url, title="", source_url="")
            fresh = await cqggzy_crawler.fetch_detail(tender)
            if fresh.full_content and len(fresh.full_content) > 30:
                try:
                    db.update_full_content(
                        url,
                        fresh.full_content,
                        fresh.content_preview or fresh.full_content[:300]
                    )
                    written += 1
                except Exception as e:
                    print(f"  ⚠️ update_full_content failed for {url}: {e}")
    print(f"📊 写回 DB {written} 条")

    # 7. DB 验证
    with engine.connect() as conn:
        after = conn.execute(text("""
            SELECT COUNT(*) FROM projects_cqggzy
            WHERE publish_date = '2026-06-08'
              AND url ~ '/trade/014005/[0-9]{16}'
              AND length(content_preview) > 0
        """)).scalar()
    print(f"📊 DB 中 6-8 014005 数字 ID 有 content_preview: {after} 条")

    await cqggzy_crawler.close() if hasattr(cqggzy_crawler, 'close') else None
    await ccgp_crawler.close() if hasattr(ccgp_crawler, 'close') else None
    await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
