"""search_parser 单测 — 覆盖正/负关键词、多分隔符、边界条件。"""

import pytest

from app.utils.search_parser import parse_keyword, match_item


class TestParseKeyword:
    """parse_keyword 输入 -> (positives, negatives) 输出。"""

    def test_empty(self):
        assert parse_keyword("") == ([], [])
        assert parse_keyword(None) == ([], [])
        assert parse_keyword("   ") == ([], [])

    def test_single_positive(self):
        assert parse_keyword("AI") == (["ai"], [])

    def test_multiple_positives_space(self):
        pos, neg = parse_keyword("AI 智能")
        assert pos == ["ai", "智能"]
        assert neg == []

    def test_multiple_positives_comma(self):
        pos, neg = parse_keyword("AI,智能,开源")
        assert pos == ["ai", "智能", "开源"]
        assert neg == []

    def test_mixed_separators(self):
        pos, neg = parse_keyword("AI 智能,开源 模型")
        assert pos == ["ai", "智能", "开源", "模型"]
        assert neg == []

    def test_single_negative(self):
        pos, neg = parse_keyword("-音频")
        assert pos == []
        assert neg == ["音频"]

    def test_positive_with_negative(self):
        pos, neg = parse_keyword("AI -音频")
        assert pos == ["ai"]
        assert neg == ["音频"]

    def test_multi_pos_multi_neg(self):
        pos, neg = parse_keyword("AI 智能 -音频 -开源")
        assert pos == ["ai", "智能"]
        assert neg == ["音频", "开源"]

    def test_dash_only_ignored(self):
        """`-` 单独出现视为无效（无负关键词实体）"""
        pos, neg = parse_keyword("-")
        assert pos == []
        assert neg == []

        pos, neg = parse_keyword("AI - -")
        assert pos == ["ai"]
        assert neg == []

    def test_dedup_preserves_order(self):
        pos, neg = parse_keyword("AI 智能 AI 智能 -音频 -音频")
        assert pos == ["ai", "智能"]
        assert neg == ["音频"]

    def test_collapses_extra_whitespace(self):
        pos, neg = parse_keyword("   AI    智能   -  音频  ")
        # 内部空格会切分 "  音频" 也被切成 "音频" (因为以 - 开头)
        assert pos == ["ai", "智能"]
        assert neg == ["音频"]

    def test_case_insensitive(self):
        """所有 token 转小写。"""
        pos, neg = parse_keyword("AI Intelligent -Audio")
        assert pos == ["ai", "intelligent"]
        assert neg == ["audio"]

    def test_dash_inside_token_kept(self):
        """仅前导 `-` 视为负号，中间的 `-` 是字面量。"""
        pos, neg = parse_keyword("covid-19 -flu")
        assert pos == ["covid-19"]
        assert neg == ["flu"]


class TestMatchItem:
    """match_item 文本匹配逻辑。"""

    def test_no_filter_passes(self):
        assert match_item("anything", [], []) is True

    def test_positive_match(self):
        assert match_item("ai 智能化项目", ["ai"], []) is True
        assert match_item("ai 智能化", ["ai"], []) is True

    def test_positive_miss(self):
        assert match_item("音频系统", ["ai"], []) is False

    def test_multiple_positives_or(self):
        """任一正向命中即通过"""
        assert match_item("智能音频", ["ai", "智能"], []) is True
        assert match_item("ai 视频", ["ai", "智能"], []) is True
        assert match_item("区块链", ["ai", "智能"], []) is False

    def test_negative_blocks(self):
        assert match_item("ai 音频项目", [], ["音频"]) is False
        assert match_item("ai 视频项目", [], ["音频"]) is True

    def test_pos_and_neg_combined(self):
        """正向必须命中且负向不能命中"""
        assert match_item("ai 视频", ["ai"], ["音频"]) is True
        assert match_item("ai 音频", ["ai"], ["音频"]) is False
        assert match_item("视频", ["ai"], ["音频"]) is False  # 无正向命中

    def test_multi_neg_any_block(self):
        """任一负关键词命中即排除"""
        assert match_item("ai 音频 开源", ["ai"], ["音频", "开源"]) is False
        assert match_item("ai 视频 开源", ["ai"], ["音频", "开源"]) is False
        assert match_item("ai 视频 商业", ["ai"], ["音频", "开源"]) is True
