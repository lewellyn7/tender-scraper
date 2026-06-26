#!/usr/bin/env python3
"""backfill_fahcqmu_publish_date 单元测试"""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import unittest
from datetime import date


class TestParseDate(unittest.TestCase):
    def test_dot_format(self):
        from backfill_fahcqmu_publish_date import parse_date
        self.assertEqual(parse_date("2026.06.18"), date(2026, 6, 18))
    
    def test_dash_format(self):
        from backfill_fahcqmu_publish_date import parse_date
        self.assertEqual(parse_date("2026-06-18"), date(2026, 6, 18))
    
    def test_chinese_format(self):
        from backfill_fahcqmu_publish_date import parse_date
        self.assertEqual(parse_date("2026年6月18日"), date(2026, 6, 18))
    
    def test_invalid_returns_none(self):
        from backfill_fahcqmu_publish_date import parse_date
        self.assertIsNone(parse_date(""))
        self.assertIsNone(parse_date("not a date"))
        self.assertIsNone(parse_date("13/45/2026"))


if __name__ == "__main__":
    unittest.main()