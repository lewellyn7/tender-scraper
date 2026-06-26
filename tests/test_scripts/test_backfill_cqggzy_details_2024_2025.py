#!/usr/bin/env python3
"""backfill_cqggzy_details_2024_2025 单元测试"""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import unittest


class TestMakeCp(unittest.TestCase):
    def test_empty_returns_empty(self):
        from backfill_cqggzy_details_2024_2025 import make_cp
        self.assertEqual(make_cp(""), "")
        self.assertEqual(make_cp(None), "")
    
    def test_short_returns_unchanged(self):
        from backfill_cqggzy_details_2024_2025 import make_cp
        self.assertEqual(make_cp("短文本"), "短文本")
    
    def test_long_truncates_at_300(self):
        from backfill_cqggzy_details_2024_2025 import make_cp
        text = "测试" * 200  # 400 字
        cp = make_cp(text)
        self.assertEqual(len(cp), 300)
    
    def test_breaks_at_sentence_end(self):
        from backfill_cqggzy_details_2024_2025 import make_cp
        # 句末 . 在 250 字符位置
        text = "A" * 250 + "." + "B" * 100
        cp = make_cp(text)
        # 应在 . 之后断
        self.assertTrue(cp.endswith("."))
        self.assertLess(len(cp), 300)
    
    def test_breaks_at_chinese_period(self):
        from backfill_cqggzy_details_2024_2025 import make_cp
        text = "甲" * 250 + "。" + "乙" * 100
        cp = make_cp(text)
        self.assertTrue(cp.endswith("。"))
    
    def test_normalizes_whitespace(self):
        from backfill_cqggzy_details_2024_2025 import make_cp
        text = "测试\n\n\t多  空白"
        cp = make_cp(text)
        self.assertEqual(cp, "测试 多 空白")


class TestSelectUrlsSql(unittest.TestCase):
    """测试 SQL 逻辑 (构造性测试, 不连 DB)"""
    
    def test_filter_conditions(self):
        """验证 SQL 包含正确条件"""
        with open(os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "backfill_cqggzy_details_2024_2025.py"), "r") as f:
            content = f.read()
        self.assertIn("publish_date BETWEEN %s AND %s", content)
        self.assertIn("content_preview IS NULL OR content_preview = ''", content)
        self.assertIn("full_content IS NULL OR full_content = ''", content)


if __name__ == "__main__":
    unittest.main()