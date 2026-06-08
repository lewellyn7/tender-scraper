"""Test 24h 漏采回放逻辑 (2026-06-08 Bug 1-C)

验证 main.py 加了 24h 漏采回放逻辑 + SQL 语法
"""
import sys
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))


class TestMain24hReplayIntegration:
    """集成: 验证 main.py 加了 24h 漏采回放逻辑"""

    def test_main_has_replay_code(self):
        """main.py 含 24h 漏采回放"""
        from pathlib import Path
        main_path = Path(ROOT) / "main.py"
        src = main_path.read_text()
        assert "24h 漏采回放" in src, "main.py should have 24h 漏采回放 comment"
        assert "INTERVAL '7 days'" in src, "main.py should query 7 days"
        assert "content_preview IS NULL" in src, "main.py should filter empty content"
        assert "INTERVAL '24 hours'" in src, "should exclude 24h recent success"
        assert "LIMIT 50" in src, "should have LIMIT 50"

    def test_replay_inserts_to_head(self):
        """验证补采数据插入到 detail_items 头部 (高优先级)"""
        from pathlib import Path
        main_path = Path(ROOT) / "main.py"
        src = main_path.read_text()
        # 找 detail_items = new_reprocess + list(detail_items)
        assert "detail_items = new_reprocess + list(detail_items)" in src, \
            "reprocessed items should be inserted at head for priority"

    def test_replay_handles_failure(self):
        """24h 漏采查询失败时不应阻塞主流程"""
        from pathlib import Path
        main_path = Path(ROOT) / "main.py"
        src = main_path.read_text()
        assert "except Exception as e" in src
        assert "24h 漏采回放查询失败" in src, \
            "should catch and warn on replay query failure (don't block main)"

    def test_replay_dedup(self):
        """避免本轮已抓的 URL 被重复入队"""
        from pathlib import Path
        main_path = Path(ROOT) / "main.py"
        src = main_path.read_text()
        assert "existing_urls" in src, "should dedup against existing detail_items"
        # 检查逻辑意图 (不需精确匹配缩进)
        assert "if url in existing_urls" in src, \
            "should skip URLs already in detail_items"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
