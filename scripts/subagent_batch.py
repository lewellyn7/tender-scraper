#!/usr/bin/env python3
"""
Subagent batch collection — 采集 2026-05-09 的 111 条数据
按 url 分组，每个子 agent 处理一批

用法:
    docker compose exec -T web python scripts/subagent_batch.py --group 1
    docker compose exec -T web python scripts/subagent_batch.py --group 2
    ... (或用 sessions_spawn 并行运行)
"""
import argparse
import asyncio
import json
import os
from pathlib import Path

from loguru import logger
import psycopg2

from app.core.browser import StealthBrowser
from app.crawlers.cqggzy import CQGGZYCrawlerV2
from app.models.tender import TenderInfo

PROGRESS_FILE = Path(__file__).parent / ".subagent_progress.json"
DB_DSN = os.environ.get("DATABASE_URL", "postgresql://root:root123@postgres:5432/tender_scraper")


def load_progress():
    if PROGRESS_FILE.exists():
        try:
            return json.load(open(PROGRESS_FILE))
        except:
            pass
    return {"1": [], "2": [], "3": [], "4": [], "done": []}


def save_progress(data):
    json.dump(data, open(PROGRESS_FILE, "w"), indent=2, ensure_ascii=False)


async def run_group(group_num: int, urls: list):
    """运行单组采集"""
    progress = load_progress()
    group_key = str(group_num)
    processed = set(progress.get(group_key, []))
    failed = set(progress.get("failed", []))

    # 过滤未处理的
    todo = [u for u in urls if u not in processed and u not in failed]
    logger.info(f"Group {group_num}: {len(todo)}/{len(urls)} 条待采集")

    if not todo:
        logger.info(f"Group {group_num} 已完成或无需采集")
        return

    browser = StealthBrowser(headless=True, slow_mo=50)
    await browser.start()
    crawler = CQGGZYCrawlerV2(browser)

    for url in todo:
        try:
            tender = TenderInfo(
                title="（待采集）",
                url=url,
                category="gov_purchase" if "014005" in url else "engineering",
            )
            result = await crawler.fetch_detail(tender)

            # 旁路验证 DB 写入
            conn = psycopg2.connect(DB_DSN)
            cur = conn.cursor()
            conn.commit()
            cur.execute("SELECT LENGTH(full_content) FROM projects_cqggzy WHERE url=%s", (url,))
            row = cur.fetchone()
            cur.close()
            conn.close()

            if row and row[0] and row[0] > 10:
                processed.add(url)
                logger.info(f"✅ {url[:50]}... ({row[0]}字)")
            else:
                failed.add(url)
                logger.warning(f"⚠️ {url[:50]}...")

        except Exception as e:
            logger.error(f"❌ {url[:50]}: {e}")
            failed.add(url)

        # 每个后保存进度
        progress[group_key] = list(processed)
        progress["failed"] = list(failed)
        save_progress(progress)

    await browser.close()

    # 最终保存
    progress[group_key] = list(processed)
    progress["failed"] = list(failed)
    save_progress(progress)

    logger.info(f"Group {group_num} 完成！成功: {len(processed)}, 失败: {len(failed)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", type=int, required=True, choices=[1, 2, 3, 4])
    args = parser.parse_args()

    # 读取所有 2026-05-09 URLs 并分组
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    cur.execute("SELECT url FROM projects_cqggzy WHERE updated_at::date = '2026-05-09' ORDER BY url")
    all_urls = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()

    n = len(all_urls)
    chunk = n // 4
    groups = {
        1: all_urls[0:chunk],
        2: all_urls[chunk:chunk*2],
        3: all_urls[chunk*2:chunk*3],
        4: all_urls[chunk*3:],
    }

    asyncio.run(run_group(args.group, groups[args.group]))