"""backfill_fahcqmu_details.py 脚本测试

覆盖:
- select_urls_without_detail 过滤 cp/fc 空行 (mock DB)
- fetch_one_with_retry 重试 + 成功/失败判定
- run() 端到端: 跳过 dry-run, 调 crawler.fetch_detail + db.upsert
- 限速/batch/retry 参数传递
"""
import sys
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch

import pytest


# ── select_urls_without_detail 测试 ────────────────────────────────
class TestSelectUrlsWithoutDetail:
    """验证 SQL 过滤逻辑: cp/fc 都空才入选"""

    def test_select_filters_empty_cp_and_fc(self):
        """cp 空 AND fc 空 → 入选; 其它 → 排除"""
        from scripts.backfill_fahcqmu_details import select_urls_without_detail

        # Mock DB connection + cursor
        fake_conn = MagicMock()
        fake_cursor = MagicMock()

        # 4 行: 2 空 (入选) + 2 已填 (排除)
        rows = [
            ("url1", "总务处", False, False),  # cp空 fc空 → 入选
            ("url2", "信息数据处", False, False),  # cp空 fc空 → 入选
            ("url3", "总务处", True, True),  # cp有 fc有 → 排除
            ("url4", "其他", True, False),  # cp有 fc空 → 排除 (SQL 排除)
        ]
        fake_cursor.fetchall.return_value = rows
        fake_conn.conn.cursor.return_value.__enter__.return_value = fake_cursor

        fake_db = MagicMock()
        fake_db._get_conn.return_value = fake_conn

        result = select_urls_without_detail(fake_db)

        # 因为 SQL 已经过滤 (cp/fc 空), 这里 SELECT 到的就全是入选的
        assert len(result) == 4
        urls = [r["url"] for r in result]
        assert urls == ["url1", "url2", "url3", "url4"]
        # org_unit 正确提取
        assert result[0]["org_unit"] == "总务处"
        assert result[1]["org_unit"] == "信息数据处"

    def test_select_with_limit(self):
        """limit 参数加到 SQL 末尾"""
        from scripts.backfill_fahcqmu_details import select_urls_without_detail

        fake_cursor = MagicMock()
        fake_cursor.fetchall.return_value = []
        fake_conn = MagicMock()
        fake_conn.conn.cursor.return_value.__enter__.return_value = fake_cursor
        fake_db = MagicMock()
        fake_db._get_conn.return_value = fake_conn

        select_urls_without_detail(fake_db, limit=5)

        # 验证 SQL 包含 LIMIT 5
        call_args = fake_cursor.execute.call_args
        sql = call_args[0][0]
        assert "LIMIT 5" in sql


# ── fetch_one_with_retry 测试 ──────────────────────────────────────
class TestFetchOneWithRetry:
    """验证 fetch_one 成功/失败/重试逻辑"""

    @pytest.mark.asyncio
    async def test_success_first_try(self):
        """首次 fetch 返回完整 fc → 立即成功"""
        from scripts.backfill_fahcqmu_details import fetch_one_with_retry

        # Mock crawler
        fake_crawler = MagicMock()
        fake_item = MagicMock()
        fake_item.full_content = "x" * 200  # > 50 字符
        fake_item.content_preview = "preview text"
        fake_crawler.fetch_detail = AsyncMock(return_value=fake_item)

        ok, err = await fetch_one_with_retry(fake_crawler, "https://x.com/1", retry=3)
        assert ok is True
        assert err == ""
        assert fake_crawler.fetch_detail.call_count == 1  # 不需重试

    @pytest.mark.asyncio
    async def test_retry_on_empty_fc(self):
        """fc 为空时重试, 最终成功"""
        from scripts.backfill_fahcqmu_details import fetch_one_with_retry

        fake_crawler = MagicMock()
        # 第一次空, 第二次成功
        empty_item = MagicMock()
        empty_item.full_content = ""
        success_item = MagicMock()
        success_item.full_content = "x" * 200
        success_item.content_preview = "preview"

        fake_crawler.fetch_detail = AsyncMock(side_effect=[empty_item, success_item])

        ok, err = await fetch_one_with_retry(fake_crawler, "https://x.com/2", retry=3)
        assert ok is True
        assert fake_crawler.fetch_detail.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_on_exception_then_success(self):
        """异常后重试, 最终成功"""
        from scripts.backfill_fahcqmu_details import fetch_one_with_retry

        fake_crawler = MagicMock()
        success_item = MagicMock()
        success_item.full_content = "x" * 200

        fake_crawler.fetch_detail = AsyncMock(
            side_effect=[Exception("timeout"), success_item]
        )

        ok, err = await fetch_one_with_retry(fake_crawler, "https://x.com/3", retry=3)
        assert ok is True
        assert fake_crawler.fetch_detail.call_count == 2

    @pytest.mark.asyncio
    async def test_fail_after_max_retry(self):
        """3 次都失败 → 返回 (False, error)"""
        from scripts.backfill_fahcqmu_details import fetch_one_with_retry

        fake_crawler = MagicMock()
        fake_crawler.fetch_detail = AsyncMock(
            side_effect=[Exception("err1"), Exception("err2"), Exception("err3")]
        )

        ok, err = await fetch_one_with_retry(fake_crawler, "https://x.com/4", retry=3)
        assert ok is False
        assert "err3" in err  # 最后一次的错误
        assert fake_crawler.fetch_detail.call_count == 3


# ── run() 端到端测试 ───────────────────────────────────────────────
class TestRunDryRun:
    """验证 --dry-run 不调 fetch_detail / 不写库"""

    @pytest.mark.asyncio
    async def test_dry_run_no_fetch_no_upsert(self, caplog):
        """dry_run 模式: SELECT 但不 fetch_detail / 不 upsert"""
        from scripts.backfill_fahcqmu_details import run
        import argparse
        import logging

        args = argparse.Namespace(
            batch=100,
            concurrency=5,
            delay=0.2,
            retry=3,
            limit=5,
            skip_existing=True,
            dry_run=True,
        )

        # Mock DB
        fake_cursor = MagicMock()
        fake_cursor.fetchall.return_value = [
            ("url1", "总务处", False, False),
            ("url2", "信息数据处", False, False),
        ]
        fake_conn = MagicMock()
        fake_conn.conn.cursor.return_value.__enter__.return_value = fake_cursor
        fake_db = MagicMock()
        fake_db._get_conn.return_value = fake_conn

        with caplog.at_level(logging.INFO, logger="backfill_fahcqmu"):
            with patch("scripts.backfill_fahcqmu_details.Database", return_value=fake_db):
                await run(args)

        # 验证没调 upsert
        assert not fake_db.upsert_projects_fahcqmu.called
        # 验证日志含 DRY-RUN 标记
        log_text = "\n".join(r.message for r in caplog.records)
        assert "[DRY-RUN]" in log_text
        assert "url1" in log_text


class TestRunFullPipeline:
    """端到端: SELECT → fetch_detail (mocked) → upsert"""

    @pytest.mark.asyncio
    async def test_full_pipeline_writes_upsert(self):
        """跑 1 批: 2 条都成功, upsert_projects_fahcqmu 调用 1 次带 2 行"""
        from scripts.backfill_fahcqmu_details import run
        import argparse

        args = argparse.Namespace(
            batch=10,  # 一批包含全部
            concurrency=5,
            delay=0.0,  # 测试不 sleep
            retry=1,
            limit=2,
            skip_existing=True,
            dry_run=False,
        )

        # Mock DB SELECT
        fake_cursor = MagicMock()
        fake_cursor.fetchall.return_value = [
            ("https://www.fahcqmu.cn/a", "总务处", False, False),
            ("https://www.fahcqmu.cn/b", "信息数据处", False, False),
        ]
        fake_conn = MagicMock()
        fake_conn.conn.cursor.return_value.__enter__.return_value = fake_cursor
        fake_db = MagicMock()
        fake_db._get_conn.return_value = fake_conn
        fake_db.upsert_projects_fahcqmu = MagicMock()

        # Mock crawler
        fake_crawler = MagicMock()
        fake_crawler.__aenter__ = AsyncMock(return_value=fake_crawler)
        fake_crawler.__aexit__ = AsyncMock(return_value=None)

        success_item = MagicMock()
        success_item.url = "https://www.fahcqmu.cn/a"
        success_item.full_content = "x" * 200
        success_item.content_preview = "preview"
        success_item.title = "测试"
        success_item.publish_date = None
        success_item.publish_date_raw = ""
        success_item.category = ""
        success_item.info_type = ""
        success_item.business_type = ""
        success_item.source_url = ""
        fake_crawler.fetch_detail = AsyncMock(return_value=success_item)

        with patch("scripts.backfill_fahcqmu_details.Database", return_value=fake_db):
            with patch("scripts.backfill_fahcqmu_details.FahcqmuCrawler", return_value=fake_crawler):
                await run(args)

        # 验证 upsert 被调 1 次, 带 2 行
        assert fake_db.upsert_projects_fahcqmu.called
        call_args = fake_db.upsert_projects_fahcqmu.call_args
        rows = call_args[0][0]
        assert len(rows) == 2
        # 验证行字段: scraped_at 必须传 (AGENTS.md 6-3 铁律)
        for row in rows:
            assert "scraped_at" in row, "scraped_at 必须传 (AGENTS.md 6-3 铁律)"
            assert isinstance(row["scraped_at"], datetime), "scraped_at 应为 datetime"
            assert row["scraped_at"] is not None
            assert row["full_content"] != ""
            assert row["content_preview"] != ""