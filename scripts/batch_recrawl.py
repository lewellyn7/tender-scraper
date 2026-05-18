#!/usr/bin/env python3
"""
分批次重新采集脚本 (v2)
- 读取数据库已有 URL
- 调用 crawler.fetch_detail() 重新采集
- 自动更新 full_content + project_overview
- 进度持久化，中断可续

用法:
    docker compose exec web python scripts/batch_recrawl.py --source cqggzy --batch-size 10 --delay 5
    docker compose exec web python scripts/batch_recrawl.py --source cqggzy --batch-size 10 --delay 5 --max-batches 3
    docker compose exec web python scripts/batch_recrawl.py --source cqggzy --retry-failed
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
from app.crawlers.ccgp import CCGPCrawlerV3
from app.models.tender import TenderInfo

PROGRESS_FILE = Path(__file__).parent / ".batch_recrawl_progress.json"
DB_DSN = os.environ.get("DATABASE_URL", "postgresql://root:root123@postgres:5432/tender_scraper")


def load_progress(source: str):
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get(source, {"processed": [], "failed": [], "done": False})
        except Exception:
            pass
    return {"processed": [], "failed": [], "done": False}


def save_progress(source: str, progress: dict):
    try:
        data = {}
        if PROGRESS_FILE.exists():
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
    except Exception:
        data = {}
    data[source] = progress
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"💾 进度：已处理 {len(progress['processed'])} 条，失败 {len(progress['failed'])} 条")


async def run_batch(source: str, batch_size: int, delay: int, retry_failed: bool, max_batches: int | None):
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    # 加载进度
    progress = load_progress(source)
    processed_set = set(progress.get("processed", []))
    failed_set = set(progress.get("failed", []))
    done = progress.get("done", False)

    if done and not retry_failed:
        logger.info("✅ 已完成。删除进度文件或使用 --retry-failed 重新运行")
        cur.close()
        conn.close()
        return

    # 获取 URL 列表
    table = "projects_cqggzy" if source == "cqggzy" else "projects_ccgp"
    cur.execute(f"SELECT url FROM {table}")
    all_urls = [row[0] for row in cur.fetchall()]
    logger.info(f"📊 数据库共 {len(all_urls)} 条记录")

    if retry_failed:
        urls = list(failed_set)
        logger.info(f"🔄 重试失败记录：{len(urls)} 条")
    else:
        urls = [u for u in all_urls if u not in processed_set and u not in failed_set]
        logger.info(f"📋 待采集：{len(urls)} 条（已处理 {len(processed_set)}，失败 {len(failed_set)}）")

    if not urls:
        logger.info("✅ 无需采集")
        cur.close()
        conn.close()
        return

    # 分批
    batches = [urls[i:i + batch_size] for i in range(0, len(urls), batch_size)]

    # 启动浏览器
    logger.info("🚀 启动浏览器...")
    browser = StealthBrowser(headless=True, slow_mo=50)
    await browser.start()
    crawler = CQGGZYCrawlerV2(browser) if source == "cqggzy" else CCGPCrawlerV3(browser)

    batch_num = 0
    for batch in batches:
        if max_batches and batch_num >= max_batches:
            logger.info(f"⏹️ 达到最大批次数 {max_batches}，停止")
            break

        batch_num += 1
        logger.info(f"\n{'=' * 50}\n📦 第 {batch_num}/{len(batches)} 批 ({len(batch)} 条)\n{'=' * 50}")

        for url in batch:
            try:
                tender = TenderInfo(
                    title="（待采集）",
                    url=url,
                    category="gov_purchase" if "014005" in url else "engineering",
                )
                if source == "ccgp":
                    tender.category = "采购公告"
                    if "intention" in url:
                        tender.category = "采购意向"
                    elif "result" in url:
                        tender.category = "结果公告"

                logger.info(f"🔍 {url[:70]}...")
                result = await crawler.fetch_detail(tender)

                if result and result.title and result.title != "（待采集）":
                    processed_set.add(url)
                    content_len = len(result.full_content) if result.full_content else 0
                    logger.info(f"✅ {result.title[:40]}... | content:{content_len}")
                else:
                    # 旁路验证：检查 DB 是否已写入
                    conn.commit()  # 确保看到最新写入
                    cur.execute("SELECT title, LENGTH(full_content) FROM projects_cqggzy WHERE url=%s", (url,))
                    row = cur.fetchone()
                    if row and row[1] and row[1] > 10:
                        processed_set.add(url)
                        logger.info(f"✅ DB确认：{row[0][:40]}... ({row[1]}字)")
                    else:
                        failed_set.add(url)
                        logger.warning(f"⚠️ 无数据 (result.title={getattr(result, 'title', None) if result else None})")

            except Exception as e:
                logger.error(f"❌ 失败：{e}")
                failed_set.add(url)

        # 保存进度
        progress["processed"] = list(processed_set)
        progress["failed"] = list(failed_set)
        save_progress(source, progress)

        # 批次间延时
        if batch_num < len(batches):
            logger.info(f"⏱️  延时 {delay}s...")
            await asyncio.sleep(delay)

    cur.close()
    conn.close()

    # 关闭浏览器
    await browser.close()

    # 完成
    progress["done"] = True
    save_progress(source, progress)

    logger.info(f"\n✅ 完成！成功: {len(processed_set)}, 失败: {len(failed_set)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["cqggzy", "ccgp"], required=True)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--delay", type=int, default=5)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--max-batches", type=int, default=None)
    args = parser.parse_args()

    asyncio.run(run_batch(args.source, args.batch_size, args.delay, args.retry_failed, args.max_batches))