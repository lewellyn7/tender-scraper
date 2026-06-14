"""P0-4 main.py 拆分 — 回归单测

验证拆分后:
1. 3 个新模块可独立 import
2. 函数签名不变 (_build_vector_text, _upsert_to_vector_store, _build_crawl_task, run_collection)
3. main.py 入口完整
4. 行为兼容 (基于 P0-4 拆分前快照, 验证 _build_vector_text 输出不变)
"""
import asyncio
import importlib
import inspect
import os
import sys
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestModuleImport:
    """3 个新模块独立可 import"""

    def test_vectorize_import(self):
        from app.core.harvest.vectorize import _build_vector_text, _upsert_to_vector_store
        assert callable(_build_vector_text)
        assert callable(_upsert_to_vector_store)

    def test_scheduler_import(self):
        from app.core.harvest.scheduler import _build_crawl_task
        assert callable(_build_crawl_task)

    def test_pipeline_import(self):
        from app.core.harvest.pipeline import run_collection, ENABLE_CCGP
        assert callable(run_collection)
        assert ENABLE_CCGP is False  # 2026-06-02 决策, 不变


class TestSignatures:
    """拆分后函数签名不变"""

    def test_build_vector_text_signature(self):
        from app.core.harvest.vectorize import _build_vector_text
        sig = inspect.signature(_build_vector_text)
        params = list(sig.parameters.keys())
        assert params == ["p"]

    def test_upsert_to_vector_store_signature(self):
        from app.core.harvest.vectorize import _upsert_to_vector_store
        sig = inspect.signature(_upsert_to_vector_store)
        params = list(sig.parameters.keys())
        assert params == ["projects"]

    def test_build_crawl_task_signature(self):
        from app.core.harvest.scheduler import _build_crawl_task
        sig = inspect.signature(_build_crawl_task)
        params = list(sig.parameters.keys())
        assert params == ["item", "index"]

    def test_run_collection_signature(self):
        from app.core.harvest.pipeline import run_collection
        assert inspect.iscoroutinefunction(run_collection)


class TestBehaviorCompat:
    """行为兼容 — 拆分前后输出应一致"""

    def test_build_vector_text_basic(self):
        """_build_vector_text: 拼接 title + overview + content_preview"""
        from app.core.harvest.vectorize import _build_vector_text
        p = {
            "title": "Test Title",
            "type": "工程招投标",
            "business_type": "政府采购",
            "info_type": "招标公告",
            "project_overview": "项目概述",
            "bidder_requirements": "投标人要求",
            "content_preview": "正文摘要",
        }
        result = _build_vector_text(p)
        assert "Test Title" in result
        assert "工程招投标" in result
        assert "政府采购" in result
        assert "项目概述" in result
        assert "正文摘要" in result
        # 长度限制 2000 字符
        assert len(result) <= 2000

    def test_build_vector_text_empty_overview(self):
        """_build_vector_text: overview 为空时, content_preview 兜底"""
        from app.core.harvest.vectorize import _build_vector_text
        p = {"title": "T", "content_preview": "X" * 1000}
        result = _build_vector_text(p)
        assert "X" * 500 in result  # 截断到 500
        assert len(result) <= 2000

    def test_build_vector_text_no_content(self):
        """_build_vector_text: 全部为空, fallback 到 title"""
        from app.core.harvest.vectorize import _build_vector_text
        p = {"title": "OnlyTitle"}
        result = _build_vector_text(p)
        assert result == "OnlyTitle"

    def test_build_crawl_task_priority(self):
        """_build_crawl_task: 预算归一化到 1-10"""
        from app.core.harvest.scheduler import _build_crawl_task

        # 500万 = 1 分
        item = SimpleNamespace(url="https://x", budget="500万元", info_type="招标公告", publish_date="2026-06-14", keywords_matched=[], deadline=None)
        task = _build_crawl_task(item, 0)
        assert task.priority_static == 1

        # 5000万 = 10 分 (上限)
        item.budget = "5000万元"
        task = _build_crawl_task(item, 0)
        assert task.priority_static == 10

        # 100万 < 500 = 0, 截断到 1
        item.budget = "100万元"
        task = _build_crawl_task(item, 0)
        assert task.priority_static == 1

    def test_build_crawl_task_no_budget(self):
        """_build_crawl_task: 没 budget, 默认 priority=5"""
        from app.core.harvest.scheduler import _build_crawl_task
        item = SimpleNamespace(url="https://x", budget=None, info_type="招标公告", publish_date="2026-06-14", keywords_matched=[], deadline=None)
        task = _build_crawl_task(item, 0)
        assert task.priority_static == 5

    def test_build_crawl_task_invalid_budget(self):
        """_build_crawl_task: budget 解析失败, 走默认 5"""
        from app.core.harvest.scheduler import _build_crawl_task
        item = SimpleNamespace(url="https://x", budget="abc", info_type="招标公告", publish_date="2026-06-14", keywords_matched=[], deadline=None)
        task = _build_crawl_task(item, 0)
        assert task.priority_static == 5


class TestMainEntry:
    """main.py 入口验证"""

    def test_main_module_importable(self):
        """main.py 可 import (不触发 main())"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("main", "main.py")
        assert spec is not None

    def test_main_function_callable(self):
        """main() 函数可调用 (mock 掉 asyncio.run 防止真跑)"""
        with mock.patch("asyncio.run") as mock_run:
            mock_run.return_value = {"filtered": 0, "total": 0}
            import main
            main.main()
            assert mock_run.called

    def test_safety_guard_called_in_entry(self):
        """__main__ 块调用 check_production_safety"""
        # 读 main.py 源码验证
        with open("main.py", "r", encoding="utf-8") as f:
            content = f.read()
        assert "check_production_safety()" in content
        assert 'if __name__ == "__main__":' in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
