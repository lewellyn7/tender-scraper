"""增量 retry 回测 — 针对 backfill 失败的 ID（HTTP 400 网站限流）

lesson 25: 网站限流 HTTP 400 + 增量 retry 机制
- 从 DB 找出 full_content = '' 或 = content_preview 且 source_id IS NOT NULL 的
- 重新调详情 API（增加 retry delay）
- UPDATE DB
- 用法: docker exec tender-scraper-collector python3 -u /tmp/backfill_retry.py
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

    conn = psycopg2.connect(
        host="postgres",
        port=5432,
        user="root",
        password="root123",
        database="tender_scraper",
    )
    cur = conn.cursor()

    # 找还没更新的: full_content 短（< 100 chars）或 = content_preview
    cur.execute("""
        SELECT id, source_id, source_type, LENGTH(full_content) AS cur_len
        FROM projects_ccgp_intention_demand
        WHERE source_id IS NOT NULL AND source_id != ''
          AND (LENGTH(full_content) < 100 OR full_content = content_preview)
        ORDER BY scraped_at DESC
    """)
    rows = cur.fetchall()
    logger.info(f"待 retry: {len(rows)} 条")

    if not rows:
        logger.info("无待 retry, 退出")
        return

    # 慢速 retry: concurrency=2, delay=2s, retries=5
    sem = asyncio.Semaphore(2)
    success = 0
    still_fail = 0
    start = time.time()
    update_batch = []
    BATCH_SIZE = 20

    async def retry_one(row, session):
        nonlocal success, still_fail
        id_, source_id, source_type, cur_len = row
        async with sem:
            await asyncio.sleep(2.0)  # 慢速, 避限流
            detail_data = await _fetch_detail_json(
                session, str(source_id), int(source_type), retries=5
            )
            if detail_data is None:
                still_fail += 1
                return
            detail_list = detail_data.get("intentionDetaileList") or []
            if not detail_list:
                still_fail += 1
                return

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
                (d.get("depict") or d.get("content") or "").strip()
                for d in detail_list
            )

            update_batch.append((str(source_id), new_full, new_preview, tender_content))
            success += 1
            if success % 10 == 0:
                elapsed = time.time() - start
                rate = success / elapsed if elapsed > 0 else 0
                logger.info(f"retry 进度: success={success} still_fail={still_fail} "
                            f"rate={rate:.2f}/s elapsed={elapsed:.0f}s")

    async with aiohttp.ClientSession() as session:
        tasks = [retry_one(r, session) for r in rows]
        await asyncio.gather(*tasks, return_exceptions=True)

    elapsed = time.time() - start
    logger.info(f"retry 完成: success={success}/{len(rows)} still_fail={still_fail} "
                f"elapsed={elapsed:.0f}s")

    if update_batch:
        logger.info(f"开始 DB UPDATE {len(update_batch)} 条...")
        for i, (source_id, new_full, new_preview, tender_content) in enumerate(update_batch):
            cur.execute(
                """UPDATE projects_ccgp_intention_demand
                   SET full_content=%s, content_preview=%s, tender_content=%s
                   WHERE source_id=%s""",
                (new_full, new_preview, tender_content, source_id),
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