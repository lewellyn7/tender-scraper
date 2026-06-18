"""
test_analysis.py — analysis API 工具函数 + SQL 单测

覆盖:
- _quarter_range 季度日期计算
- _resolve_period 参数解析
- _category_filter category → info_type SQL 转换
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.api.routes.analysis import _quarter_range, _resolve_period, _category_filter


# ─── _quarter_range ─────────────────────────────────────────────────────────

def test_quarter_range_Q1():
    d_start, d_end = _quarter_range(2026, 1)
    assert d_start == date(2026, 1, 1)
    assert d_end == date(2026, 3, 31)


def test_quarter_range_Q2():
    d_start, d_end = _quarter_range(2026, 2)
    assert d_start == date(2026, 4, 1)
    assert d_end == date(2026, 6, 30)


def test_quarter_range_Q3():
    d_start, d_end = _quarter_range(2026, 3)
    assert d_start == date(2026, 7, 1)
    assert d_end == date(2026, 9, 30)


def test_quarter_range_Q4():
    d_start, d_end = _quarter_range(2026, 4)
    assert d_start == date(2026, 10, 1)
    assert d_end == date(2026, 12, 31)


def test_quarter_range_invalid():
    try:
        _quarter_range(2026, 5)
        assert False, "应该抛 ValueError"
    except ValueError:
        pass


# ─── _resolve_period ────────────────────────────────────────────────────────

def test_resolve_period_quarter():
    d_start, d_end, desc = _resolve_period("quarter", 2026, 2, None, None)
    assert d_start == date(2026, 4, 1)
    assert d_end == date(2026, 6, 30)
    assert desc["label"] == "2026 Q2"


def test_resolve_period_quarter_缺参():
    try:
        _resolve_period("quarter", None, None, None, None)
        assert False
    except ValueError:
        pass


def test_resolve_period_year():
    d_start, d_end, desc = _resolve_period("year", 2026, None, None, None)
    assert d_start == date(2026, 1, 1)
    assert d_end == date(2026, 12, 31)
    assert desc["label"] == "2026 年"


def test_resolve_period_custom():
    d_start, d_end, desc = _resolve_period(
        "custom", None, None, date(2026, 1, 1), date(2026, 3, 31)
    )
    assert d_start == date(2026, 1, 1)
    assert d_end == date(2026, 3, 31)
    assert "2026-01-01" in desc["label"]


def test_resolve_period_invalid():
    try:
        _resolve_period("week", 2026, None, None, None)
        assert False
    except ValueError:
        pass


# ─── _category_filter ───────────────────────────────────────────────────────

def test_category_filter_政府采购():
    sql = _category_filter("政府采购")
    assert sql == "info_type = '采购结果公告'"


def test_category_filter_工程招投标():
    sql = _category_filter("工程招投标")
    assert "中标候选人公示" in sql
    assert "中标结果公示" in sql


def test_category_filter_invalid():
    try:
        _category_filter("xxx")
        assert False
    except ValueError:
        pass