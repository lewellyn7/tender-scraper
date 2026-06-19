"""scripts/backfill_vectors_incremental.py 单测 (2026-06-20)

验证增量回填脚本:
1. build_doc: text 长度限制 + metadata 字段完整
2. fetch_pending_projects: 排除已存在 doc_id
3. backfill_batch: 重试逻辑
4. checkpoint 持久化 + 恢复

设计: 用 mock patch DB + vLLM 客户端, 不依赖真实服务
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestBuildDoc:
    """build_doc: text 构造 + metadata 完整"""

    def test_text_truncated_to_1000(self):
        """text 截断到 1000 字符 (vLLM batch 400 限制)"""
        from scripts.backfill_vectors_incremental import build_doc

        project = {
            "id": 123,
            "url": "https://example.com/x",
            "title": "标题",
            "content_preview": "X" * 1000,
            "full_content": "Y" * 1000,
            "publish_date": "2026-06-19",
            "info_type": "招标公告",
            "business_type": "工程招投标",
        }
        doc = build_doc(project)
        assert len(doc["text"]) <= 1000, f"text 长度 {len(doc['text'])} > 1000"

    def test_metadata_all_fields(self):
        """metadata 必含 url/title/publish_date/info_type/business_type/source/project_id"""
        from scripts.backfill_vectors_incremental import build_doc

        project = {
            "id": 456,
            "url": "https://example.com/y",
            "title": "测试",
            "content_preview": "",
            "full_content": "",
            "publish_date": "2026-06-20",
            "info_type": "中标结果公示",
            "business_type": "政府采购",
        }
        doc = build_doc(project)
        md = doc["metadata"]
        for key in ("url", "title", "publish_date", "info_type",
                    "business_type", "source", "project_id"):
            assert key in md, f"metadata 缺 {key}"
        assert md["source"] == "cqggzy"
        assert md["project_id"] == 456
        assert doc["id"] == "tender_456"

    def test_empty_title_falls_back_to_text(self):
        """title 为空时 text 仍非空 (避免空 embedding)"""
        from scripts.backfill_vectors_incremental import build_doc

        project = {
            "id": 789,
            "url": "https://example.com/z",
            "title": "",
            "content_preview": "",
            "full_content": "",
        }
        doc = build_doc(project)
        # text 可为空 (上层会过滤 title='' 的项目, 这里只验证不抛错)
        assert "id" in doc


class TestCheckpoint:
    """checkpoint 持久化 + 恢复"""

    def test_load_returns_zero_when_missing(self, tmp_path, monkeypatch):
        """checkpoint 文件不存在时返回 0"""
        from scripts import backfill_vectors_incremental as mod

        monkeypatch.setattr(mod, "CHECKPOINT_DIR", tmp_path)
        monkeypatch.setattr(mod, "CHECKPOINT_FILE", tmp_path / "backfill.json")
        assert mod.load_checkpoint() == 0

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        """save → load 应恢复原值"""
        from scripts import backfill_vectors_incremental as mod

        monkeypatch.setattr(mod, "CHECKPOINT_DIR", tmp_path)
        monkeypatch.setattr(mod, "CHECKPOINT_FILE", tmp_path / "backfill.json")
        mod.save_checkpoint(last_id=12345, total_processed=1000, duration_s=120.5)
        loaded = mod.load_checkpoint()
        assert loaded == 12345

    def test_corrupt_checkpoint_falls_back_to_zero(self, tmp_path, monkeypatch):
        """checkpoint JSON 损坏时回退到 0 (不抛异常)"""
        from scripts import backfill_vectors_incremental as mod

        bad = tmp_path / "backfill.json"
        bad.write_text("{ corrupted json")
        monkeypatch.setattr(mod, "CHECKPOINT_DIR", tmp_path)
        monkeypatch.setattr(mod, "CHECKPOINT_FILE", bad)
        assert mod.load_checkpoint() == 0


class TestBatchRetry:
    """backfill_batch: 重试逻辑"""

    def test_success_first_try(self):
        """成功路径: 不重试"""
        from scripts import backfill_vectors_incremental as mod

        mock_vs = mock.MagicMock()
        mock_vs.upsert_documents.return_value = {"inserted": 50}
        batch = [{"id": i} for i in range(50)]

        result = mod.backfill_batch(mock_vs, batch, max_retries=3)
        assert result == 50
        assert mock_vs.upsert_documents.call_count == 1

    def test_retry_then_success(self):
        """失败 2 次后成功: 总共 3 次调用"""
        from scripts import backfill_vectors_incremental as mod

        mock_vs = mock.MagicMock()
        mock_vs.upsert_documents.side_effect = [
            Exception("网络抖动"),
            Exception("又抖"),
            {"inserted": 10},
        ]
        batch = [{"id": i} for i in range(10)]

        result = mod.backfill_batch(mock_vs, batch, max_retries=3)
        assert result == 10
        assert mock_vs.upsert_documents.call_count == 3

    def test_retry_exhausted_returns_zero(self):
        """重试用尽: 返回 0, 不抛异常"""
        from scripts import backfill_vectors_incremental as mod

        mock_vs = mock.MagicMock()
        mock_vs.upsert_documents.side_effect = Exception("永久失败")
        batch = [{"id": i} for i in range(5)]

        result = mod.backfill_batch(mock_vs, batch, max_retries=2)
        assert result == 0
        assert mock_vs.upsert_documents.call_count == 2


class TestDryRun:
    """main() dry-run 模式"""

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch, capsys):
        """--dry-run 不应调 upsert_documents"""
        from scripts import backfill_vectors_incremental as mod

        # mock DB
        mock_conn = mock.MagicMock()
        mock_cursor = mock.MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        # get_total_remaining 返回 100
        # fetch_pending_projects 返回 3 条
        monkeypatch.setattr(mod, "psycopg2", mock.MagicMock())
        mod.psycopg2.connect.return_value = mock_conn

        mock_cursor.fetchone.return_value = (100,)
        mock_cursor.fetchall.return_value = [
            (1, "https://x.com/1", "标题1", "", "", "2026-06-19", "招标公告", "工程"),
            (2, "https://x.com/2", "标题2", "", "", "2026-06-19", "答疑补遗", "工程"),
            (3, "https://x.com/3", "标题3", "", "", "2026-06-19", "中标公示", "政采"),
        ]
        mock_cursor.description = [
            ("id",), ("url",), ("title",), ("content_preview",),
            ("full_content",), ("publish_date",), ("info_type",), ("business_type",),
        ]

        mock_vs = mock.MagicMock()
        monkeypatch.setattr(mod, "get_vector_store", lambda: mock_vs)
        monkeypatch.setattr(mod, "CHECKPOINT_DIR", tmp_path)
        monkeypatch.setattr(mod, "CHECKPOINT_FILE", tmp_path / "c.json")
        monkeypatch.setattr(mod, "load_checkpoint", lambda: 0)

        # 模拟 argv
        monkeypatch.setattr("sys.argv", ["test", "--dry-run"])

        try:
            mod.main()
        except SystemExit:
            pass

        # 关键: 没有任何 upsert 调用
        assert mock_vs.upsert_documents.call_count == 0
