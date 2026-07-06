"""重庆烟草采集器单元测试 (7-06 新增)"""
import sys
from pathlib import Path

# Allow running tests from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.crawlers.cqyc import (
    classify_by_title,
    parse_date_from_url,
    build_list_url,
    INFO_TYPE_KEYWORDS,
)


def test_classify_result_notice():
    """结果公示分类"""
    assert classify_by_title("成交结果公告") == "result_notice"
    assert classify_by_title("谈判结果公示") == "result_notice"
    assert classify_by_title("中标候选人公示") == "result_notice"
    assert classify_by_title("中选结果公示") == "result_notice"
    assert classify_by_title("结果公告") == "result_notice"
    assert classify_by_title("结果公示表") == "result_notice"


def test_classify_purchase_notice():
    """采购公告分类"""
    assert classify_by_title("采购公告") == "purchase_notice"
    assert classify_by_title("询价公告") == "purchase_notice"
    assert classify_by_title("采购邀请函") == "purchase_notice"
    assert classify_by_title("竞争性谈判公告") == "purchase_notice"
    assert classify_by_title("竞争谈判公告") == "purchase_notice"
    assert classify_by_title("公开招标公告") == "purchase_notice"


def test_classify_change_notice():
    """变更公告分类"""
    assert classify_by_title("变更公示") == "change_notice"
    assert classify_by_title("变更补遗") == "change_notice"
    assert classify_by_title("澄清补遗") == "change_notice"
    assert classify_by_title("澄清说明") == "change_notice"


def test_classify_failed_notice():
    """流标分类"""
    assert classify_by_title("流标公示") == "failed_notice"
    assert classify_by_title("流标公示表") == "failed_notice"
    assert classify_by_title("流标公告") == "failed_notice"


def test_classify_rental_notice():
    """招租公告分类"""
    assert classify_by_title("招租公告") == "rental_notice"
    assert classify_by_title("招租结果公示") == "rental_notice"


def test_classify_other():
    """无法分类时归为 other"""
    assert classify_by_title("完全无关的标题") == "other"
    assert classify_by_title("") == "other"


def test_classify_priority():
    """关键词顺序匹配 (结果优先于采购)"""
    # 标题 "结果公告" 应被识别为 result_notice 而非 other
    assert classify_by_title("重庆烟草项目结果公告") == "result_notice"


def test_parse_date_from_url():
    """从 URL /a/YYYYMMDD/uuid.html 解析日期"""
    from datetime import date
    assert parse_date_from_url("https://www.966599.com/a/20260706/abc-123.html") == date(2026, 7, 6)
    assert parse_date_from_url("/a/20251231/uuid.html") == date(2025, 12, 31)
    assert parse_date_from_url("https://other.com/no-date.html") is None
    assert parse_date_from_url("") is None


def test_build_list_url():
    """列表页 URL 构造 (page 1 vs N>=2)"""
    assert build_list_url(1) == "https://www.966599.com/c/4/"
    assert build_list_url(2) == "https://www.966599.com/c/4/2"
    assert build_list_url(100) == "https://www.966599.com/c/4/100"
    # page 0 / negative 走 page=1 分支
    assert build_list_url(0) == "https://www.966599.com/c/4/"


def test_all_categories_covered():
    """5 大分类 + other 都有定义"""
    expected_types = {"result_notice", "purchase_notice", "change_notice", "failed_notice", "rental_notice"}
    assert set(INFO_TYPE_KEYWORDS.keys()) == expected_types
    # 每个分类至少 1 个关键词
    for info_type, keywords in INFO_TYPE_KEYWORDS.items():
        assert len(keywords) > 0, f"{info_type} 没有关键词"