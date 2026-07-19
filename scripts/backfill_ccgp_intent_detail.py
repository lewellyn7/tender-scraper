"""回测 ccgp-intent 详情 API 抓全 (按 #27908 "2" + #27907 plan)

lesson 22+ A2: 调详情 API 拿 intentionDetaileList[] 真全文 + UPDATE DB
- 1855 条 (post smoke) 并发 5 + retry 3 + delay 0.5s
- baseline: avg full_content=38 chars (仅 depict)
- 目标: avg full_content ~225 chars (+490%)
"""
import asyncio
import sys
import time

sys.path.insert(0, '/app')

import aiohttp
from loguru import logger

from app.crawlers.ccgp_intent_demand import _fetch_detail_json, format_detail_list


async def main():
    import psycopg2
    from psycopg2.extras import RealDictCursor

    # 1. 取所有 source_id + source_type
    conn = psycopg2.connect(
        host="postgres",
        port=5432,
        user="root",
        password="root123",  # collector 容器内 DATABASE_URL = root:root123
        database="tender_scraper",
    )
    cur = conn.cursor()
    cur.execute("""
        SELECT source_id, source_type
        FROM projects_ccgp_intention_demand
        WHERE source_id IS NOT NULL AND source_id != ''
        ORDER BY scraped_at DESC
    """)
    rows = cur.fetchall()
    logger.info(f"DB rows: {len(rows)}")
    if not rows:
        logger.warning("DB 无 source_id 数据, 退出")
        return

    # 2. 并发调详情 API + 拼装新 full_content + UPDATE
    sem = asyncio.Semaphore(5)
    success = 0
    fail = 0
    start = time.time()
    update_batch = []
    BATCH_SIZE = 50

    async def update_one(row, session):
        nonlocal success, fail
        source_id, source_type = row
        async with sem:
            await asyncio.sleep(0.5)  # 限速
            detail_data = await _fetch_detail_json(session, str(source_id), int(source_type), retries=3)
            if detail_data is None:
                fail += 1
                return
            detail_list = detail_data.get("intentionDetaileList") or []
            if not detail_list:
                fail += 1
                return

            # 拼装 full_content
            detail_text = format_detail_list(detail_list)
            depict = (detail_data.get("depict") or "").strip()
            parts = []
            if depict:
                parts.append(f"【项目简介】\n{depict}")
            if detail_text:
                parts.append(f"【采购明细】\n{detail_text}")
            new_full = "\n\n".join(parts)
            new_preview = new_full[:300] if new_full else ""
            tender_content = "\n\n".join(
                (d.get("depict") or d.get("content") or "").strip() for d in detail_list
            )

            update_batch.append((str(source_id), new_full, new_preview, tender_content))
            success += 1

            # 进度日志
            if success % 50 == 0:
                elapsed = time.time() - start
                rate = success / elapsed if elapsed > 0 else 0
                logger.info(f"进度: success={success} fail={fail} rate={rate:.1f}/s elapsed={elapsed:.0f}s")

    async with aiohttp.ClientSession() as session:
        tasks = [update_one(r, session) for r in rows]
        await asyncio.gather(*tasks, return_exceptions=True)

    elapsed = time.time() - start
    logger.info(f"详情 API 抓全完成: success={success}/{len(rows)} fail={fail} elapsed={elapsed:.0f}s")

    # 3. UPDATE DB (批量 commit)
    if update_batch:
        logger.info(f"开始 DB UPDATE {len(update_batch)} 条...")
        for i, (source_id, new_full, new_preview, tender_content) in enumerate(update_batch):
            cur.execute(
                """UPDATE projects_ccgp_intention_demand
                   SET full_content=%s, content_preview=%s, tender_content=%s
                   WHERE source_id=%s""",
                (new_full, new_preview, tender_content, source_id)
            )
            if (i + 1) % BATCH_SIZE == 0:
                conn.commit()
                logger.info(f"DB UPDATE 进度: {i+1}/{len(update_batch)} committed")
        conn.commit()
        logger.info(f"✅ DB UPDATE 完成: {len(update_batch)} 条")

    cur.close()
    conn.close()


if __name__ == "__main__":
    asyncio.run(main())