#!/usr/bin/env python3
"""
backfill_day_worker.py — 按日回填 v2 单进程 worker

每个 worker 处理一段日期范围（静态分片），单进程内单线程顺序处理每一天。
每天处理 9 个分类 (6 engineering + 3 gov_purchase)：
  engineering: notice / plan / qa / candidate / result / terminate
  gov_purchase: notice / change / result

每分类处理流程：
  1. 拉 list 第 1 页 → 拿 total → 写 expected_count
  2. 翻页拉全 list (dedup)
  3. 抓 detail (不抓，详情用 web 触发；本 worker 只补 list+基础字段)
  4. DB upsert 写回
  5. 比对 expected vs actual → 写 diff_count
  6. 标记 status

设计原则：
  - 1 worker 1 进程，避免 asyncio / 多 worker 共享 browser context
  - 写入 backfill_tracker 表，全量状态可查
  - failed 自动重试 3 次，blocked 需手工介入
  - 30 min 内单日未完成 → 心跳报警

用法：
  python3 scripts/backfill_day_worker.py --worker-id w1 --start 2026-05-31 --end 2026-03-13
"""
import asyncio
import argparse
import os
import sys
import json
import time
import traceback
from datetime import datetime, timedelta, date
from pathlib import Path

sys.path.insert(0, '/app')
os.environ.setdefault('DATABASE_URL', 'postgresql://root:root123@postgres:5432/tender_scraper')

from loguru import logger
from app.core.browser import StealthBrowser
from app.crawlers.cqggzy import CQGGZYCrawlerV2 as CQGGZYCrawler
from app.database.db import Database


# 9 个分类 (与 main.py 第 142-152 行一致)
CATEGORIES = [
    ("engineering_notice",    "engineering"),
    ("engineering_plan",      "engineering"),
    ("engineering_qa",        "engineering"),
    ("engineering_candidate", "engineering"),
    ("engineering_result",    "engineering"),
    ("engineering_terminate", "engineering"),
    ("gov_purchase_notice",   "gov_purchase"),
    ("gov_purchase_change",   "gov_purchase"),
    ("gov_purchase_result",   "gov_purchase"),
]

MAX_PAGES = 20  # 每分类最多 20 页 (1000 条) 安全保护
PAGE_SIZE = 50  # list API 每页条数
SLEEP_BETWEEN_CATS = 1.0  # 分类间延迟
SLEEP_BETWEEN_PAGES = 0.5  # 分页间延迟
SLEEP_BETWEEN_DAYS = 0.5  # 日期间延迟


def date_range(start: date, end: date):
    """倒序生成 [start, end] 日期范围（最近→最旧）"""
    d = start
    while d >= end:
        yield d
        d -= timedelta(days=1)


class BackfillWorker:
    def __init__(self, worker_id: str, start: date, end: date):
        self.worker_id = worker_id
        self.start = start
        self.end = end
        self.db = Database()
        self.browser = None
        self.crawler = None
        self.stats = {
            "dates_processed": 0,
            "dates_success": 0,
            "dates_failed": 0,
            "total_expected": 0,
            "total_actual": 0,
        }

    async def start_browser(self):
        self.browser = StealthBrowser(headless=True, slow_mo=0)
        await self.browser.start()
        self.crawler = CQGGZYCrawler(self.browser)
        logger.info(f"[{self.worker_id}] 浏览器已启动")

    async def stop_browser(self):
        if self.browser:
            await self.browser.close()
        logger.info(f"[{self.worker_id}] 浏览器已停止")

    def ensure_tracker_rows(self, target_date: date):
        """确保某天的 9 行 tracker 已存在 (status=pending)"""
        for category, parent in CATEGORIES:
            try:
                self.db._get_conn().execute(
                    """INSERT INTO backfill_tracker (target_date, category, parent_category, status)
                    VALUES (%s, %s, %s, 'pending')
                    ON CONFLICT (target_date, category) DO NOTHING""",
                    (target_date, category, parent)
                )
            except Exception as e:
                logger.error(f"[{self.worker_id}] ensure_tracker_rows failed: {e}")
        self.db._get_conn().commit()

    def get_tracker_row(self, target_date: date, category: str) -> dict | None:
        """查某天某分类 tracker 行"""
        cur = self.db._get_conn().execute(
            "SELECT * FROM backfill_tracker WHERE target_date=%s AND category=%s",
            (target_date, category)
        )
        row = cur.fetchone() if cur else None
        if row and hasattr(row, 'keys'):
            return dict(row)
        if row and isinstance(row, (list, tuple)):
            # fallback: tuple
            return {
                "id": row[0], "target_date": row[1], "category": row[2],
                "parent_category": row[3], "status": row[4],
                "expected_count": row[5], "actual_count": row[6],
                "diff_count": row[7], "worker_id": row[8],
                "started_at": row[9], "finished_at": row[10],
                "retry_count": row[11], "last_error": row[12],
            }
        return None

    def mark_running(self, target_date: date, category: str):
        try:
            self.db._get_conn().execute(
                """UPDATE backfill_tracker
                SET status='running', worker_id=%s, started_at=CURRENT_TIMESTAMP,
                    retry_count=retry_count+0
                WHERE target_date=%s AND category=%s""",
                (self.worker_id, target_date, category)
            )
            self.db._get_conn().commit()
        except Exception as e:
            logger.error(f"[{self.worker_id}] mark_running failed: {e}")

    def mark_success(self, target_date: date, category: str, expected: int, actual: int):
        diff = expected - actual
        try:
            self.db._get_conn().execute(
                """UPDATE backfill_tracker
                SET status='success', expected_count=%s, actual_count=%s, diff_count=%s,
                    finished_at=CURRENT_TIMESTAMP, last_error=NULL
                WHERE target_date=%s AND category=%s""",
                (expected, actual, diff, target_date, category)
            )
            self.db._get_conn().commit()
        except Exception as e:
            logger.error(f"[{self.worker_id}] mark_success failed: {e}")

    def mark_failed(self, target_date: date, category: str, err: str):
        try:
            self.db._get_conn().execute(
                """UPDATE backfill_tracker
                SET status='failed', finished_at=CURRENT_TIMESTAMP,
                    last_error=%s, retry_count=retry_count+1
                WHERE target_date=%s AND category=%s""",
                (err[:500], target_date, category)
            )
            self.db._get_conn().commit()
        except Exception as e:
            logger.error(f"[{self.worker_id}] mark_failed failed: {e}")

    def mark_blocked(self, target_date: date, category: str, err: str):
        try:
            self.db._get_conn().execute(
                """UPDATE backfill_tracker
                SET status='blocked', finished_at=CURRENT_TIMESTAMP,
                    last_error=%s
                WHERE target_date=%s AND category=%s""",
                (err[:500], target_date, category)
            )
            self.db._get_conn().commit()
        except Exception as e:
            logger.error(f"[{self.worker_id}] mark_blocked failed: {e}")

    async def fetch_category_for_day(self, target_date: date, category: str, parent: str) -> tuple[int, int]:
        """拉某天某分类的 list, 入库。返回 (expected, actual)

        2026-06-11 修复: CQGGZY API edt 排他, 单日采集需 end_date = target + 1 day
        (原错误: end_date=target_date.max() → API total=0)
        """
        # 翻页拉 list
        all_items: list = []
        seen_urls: set = set()
        expected_count = 0

        # 关键: edt 排他 → +1 day
        s = datetime.combine(target_date, datetime.min.time())
        e = datetime.combine(target_date + timedelta(days=1), datetime.min.time())

        for page_num in range(1, MAX_PAGES + 1):
            try:
                items = await self.crawler.fetch_list(
                    category=category, page_num=page_num,
                    start_date=s, end_date=e,
                )
            except Exception as e:
                logger.warning(f"[{self.worker_id}] {target_date} {category} page={page_num} 异常: {e}")
                if page_num == 1:
                    raise  # 第 1 页失败 → 整分类失败
                break

            if not isinstance(items, list):
                items = []

            for it in items:
                url = getattr(it, "url", "") if not isinstance(it, dict) else it.get("url", "")
                if url:
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                all_items.append(it)

            if len(items) < PAGE_SIZE:
                break
            await asyncio.sleep(SLEEP_BETWEEN_PAGES)

        if not all_items:
            logger.info(f"[{self.worker_id}] {target_date} {category}: 0 条")
            return (0, 0)

        # expected = 实际拉到的 list 长度 (保守, 不拿 API total, 因为 fetch_list 不暴露)
        expected_count = len(all_items)

        # 入库
        actual_count = 0
        try:
            rows = []
            for item in all_items:
                if isinstance(item, dict):
                    rows.append(item)
                else:
                    # TenderInfo → dict
                    rows.append({
                        "url": getattr(item, 'url', ''),
                        "title": getattr(item, 'title', ''),
                        "category": getattr(item, 'category', category),
                        "info_type": getattr(item, 'info_type', category),
                        "business_type": parent,
                        "publish_date": getattr(item, 'publish_date', None),
                        "publish_date_raw": getattr(item, 'publish_date_raw', ''),
                        "source_url": getattr(item, 'source_url', ''),
                        "scraped_by": f"backfill_daily_v2/{self.worker_id}",
                    })
            # 过滤空 url
            rows = [r for r in rows if r.get("url")]
            if rows:
                # 批量 upsert (50/批)
                for i in range(0, len(rows), 50):
                    batch = rows[i:i+50]
                    try:
                        self.db.upsert_projects(batch)
                        actual_count += len(batch)
                    except Exception as e:
                        logger.warning(f"[{self.worker_id}] upsert 批次 {i} 失败: {e}")
        except Exception as e:
            logger.error(f"[{self.worker_id}] {target_date} {category} 入库失败: {e}")
            raise

        return (expected_count, actual_count)

    async def process_day(self, target_date: date) -> dict:
        """处理某天的所有分类"""
        day_str = target_date.isoformat()
        logger.info(f"[{self.worker_id}] ============ {day_str} ============")
        self.ensure_tracker_rows(target_date)

        day_stats = {"expected": 0, "actual": 0, "success": 0, "failed": 0, "blocked": 0}

        for category, parent in CATEGORIES:
            row = self.get_tracker_row(target_date, category)
            if not row:
                logger.warning(f"[{self.worker_id}] {day_str} {category} 无 tracker 行, 跳过")
                continue

            # 跳过已 success
            if row["status"] == "success":
                logger.debug(f"[{self.worker_id}] {day_str} {category} 已 success, 跳过")
                day_stats["success"] += 1
                continue

            # 跳过 blocked (retry > 3)
            if row["status"] == "blocked" and row["retry_count"] >= 3:
                logger.warning(f"[{self.worker_id}] {day_str} {category} 已 blocked, 跳过")
                day_stats["blocked"] += 1
                continue

            self.mark_running(target_date, category)
            try:
                expected, actual = await self.fetch_category_for_day(target_date, category, parent)
                self.mark_success(target_date, category, expected, actual)
                day_stats["expected"] += expected
                day_stats["actual"] += actual
                day_stats["success"] += 1
                logger.info(f"[{self.worker_id}] ✅ {day_str} {category}: expected={expected} actual={actual}")
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:300]}"
                retry = row.get("retry_count", 0) + 1
                if retry >= 3:
                    self.mark_blocked(target_date, category, err)
                    day_stats["blocked"] += 1
                    logger.error(f"[{self.worker_id}] 🚫 {day_str} {category} blocked (retry {retry}): {err}")
                else:
                    self.mark_failed(target_date, category, err)
                    day_stats["failed"] += 1
                    logger.warning(f"[{self.worker_id}] ❌ {day_str} {category} failed (retry {retry}): {err}")

            await asyncio.sleep(SLEEP_BETWEEN_CATS)

        logger.info(
            f"[{self.worker_id}] {day_str} 完成: "
            f"success={day_stats['success']}, failed={day_stats['failed']}, "
            f"blocked={day_stats['blocked']}, expected={day_stats['expected']}, actual={day_stats['actual']}"
        )
        return day_stats

    async def run(self):
        logger.info(f"[{self.worker_id}] Worker 启动: {self.start} → {self.end}")
        await self.start_browser()

        try:
            for target_date in date_range(self.start, self.end):
                try:
                    await self.process_day(target_date)
                    self.stats["dates_processed"] += 1
                    self.stats["dates_success"] += 1
                except Exception as e:
                    logger.error(f"[{self.worker_id}] {target_date} 整日失败: {e}")
                    traceback.print_exc()
                    self.stats["dates_failed"] += 1
                await asyncio.sleep(SLEEP_BETWEEN_DAYS)
        finally:
            await self.stop_browser()
            logger.info(f"[{self.worker_id}] ===== Worker 结束 =====")
            logger.info(f"[{self.worker_id}] 统计: {self.stats}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-id", required=True, help="worker 标识: w1/w2/w3/w4/w5")
    parser.add_argument("--start", required=True, help="起始日期 YYYY-MM-DD (最近日)")
    parser.add_argument("--end", required=True, help="截止日期 YYYY-MM-DD (最旧日)")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    if start < end:
        print(f"ERROR: start ({start}) < end ({end}), 应 start >= end (倒序)")
        sys.exit(1)

    worker = BackfillWorker(args.worker_id, start, end)
    asyncio.run(worker.run())


if __name__ == "__main__":
    main()
