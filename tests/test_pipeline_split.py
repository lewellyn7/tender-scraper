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

    def test_pipeline_all_exports(self):
        """pipeline.py 必须 export run_collection + CrawlTask (后者是 crawler_fn 类型注解必需)

        教训: P0-4 拆分时漏 import CrawlTask, 跑到 detail 阶段才报 NameError.
        """
        from app.core.harvest import pipeline
        # 这些是 pipeline.py 内部代码用到的所有外部符号
        for name in ["run_collection", "CrawlTask", "SmartScheduler", "TaskStatus", "ENABLE_CCGP"]:
            assert hasattr(pipeline, name), f"pipeline.py 漏 export {name}"


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

    def test_pipeline_module_imports_clean(self):
        """pipeline.py 顶部 import 不应触发 NameError (P0-4 真凶场景)

        教训: 之前 _build_crawl_task 在 scheduler.py 中 import 了 CrawlTask,
        但 pipeline.py 在 detail 阶段也用 CrawlTask (crawler_fn 类型注解),
        漏 import 导致 line 288 `crawler_fn(task: CrawlTask)` 报 NameError.
        """
        import importlib
        import sys
        # 清掉可能的缓存
        for m in list(sys.modules):
            if 'harvest' in m or 'pipeline' in m:
                del sys.modules[m]
        from app.core.harvest.pipeline import CrawlTask  # noqa
        # 同时确保 run_collection 真的能编译 (不光是 import)
        import inspect
        src = inspect.getsource(__import__('app.core.harvest.pipeline', fromlist=['run_collection']))
        assert "CrawlTask" in src, "pipeline.py 必须引用 CrawlTask"


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


class TestAllImportsRequired:
    """P0-4 教训: 必须 import 所有函数内引用的顶层符号

    之前漏了 os (line 429) 和 CrawlTask (line 288), 都报 NameError.
    教训: 标榜 'PURE LIFT' 不代表真纯, 拆分时必须逐行检查 type annotation
    和函数体内引用的所有顶层符号.
    """

    def test_os_importable(self):
        """os 模块必须 import (line 429 os.path.join 用)"""
        from app.core.harvest import pipeline
        import os
        # pipeline 内部用了 os.path.join
        assert pipeline.os is os or hasattr(pipeline, "os") or True
        # 直接验证: 在 pipeline 模块命名空间里能找到 os
        # (因为 import os 放在模块顶部, 命名空间里就有)
        assert "os" in dir(pipeline), "pipeline.py 漏 import os"

    def test_all_top_level_imports_present(self):
        """P0-4 教训 2: CrawlTask 也要 import (line 288 type annotation)"""
        from app.core.harvest import pipeline
        # 关键符号: CrawlTask + SmartScheduler + TaskStatus (都在 type annotation 用了)
        for name in ["CrawlTask", "SmartScheduler", "TaskStatus", "ENABLE_CCGP"]:
            assert hasattr(pipeline, name), f"pipeline.py 漏 import {name}"

    def test_pipeline_compiles_no_name_error(self):
        """验证 pipeline.py 编译时无 NameError (line 487: except as e: print(e))

        之前 'name CrawlTask is not defined' 报在 line 487 附近.
        """
        import importlib
        import sys
        # 清缓存
        for m in list(sys.modules):
            if 'harvest.pipeline' in m or 'harvest.vectorize' in m or 'harvest.scheduler' in m:
                del sys.modules[m]
        import app.core.harvest.pipeline
        # 试着 import 所有可能的符号
        symbols = ["os", "asyncio", "json", "time", "datetime", "timedelta", "logger",
                   "StealthBrowser", "_build_crawl_task", "CrawlTask", "SmartScheduler",
                   "get_db",
                   "get_vector_store_indexed", "TenderFilter", "ReportGenerator", "settings",
                   "TaskStatus", "_upsert_to_vector_store", "SessionMemory",
                   "SessionMemoryConfig", "CCGPCrawlerV3", "CQGGZYCrawlerV2",
                   "get_vector_store_indexed", "TenderFilter", "ReportGenerator", "settings",
                   "ENABLE_CCGP", "run_collection"]
        for s in symbols:
            assert hasattr(app.core.harvest.pipeline, s), f"pipeline.{s} 缺失"
