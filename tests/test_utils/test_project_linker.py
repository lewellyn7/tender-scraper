"""项目匹配算法测试"""

import pytest
from app.utils.project_linker import (
    normalize_project_name,
    extract_project_no,
    match_project,
    normalize_project_no,
    get_project_key,
)


class TestNormalizeProjectName:
    """normalize_project_name 测试"""

    def test_basic(self):
        assert normalize_project_name("北京市某项目") == "北京市某项目"
        assert normalize_project_name("北京市 某 项目") == "北京市某项目"  # 空格被移除
        assert normalize_project_name("某-项目") == "某项目"

    def test_repeat_suffix(self):
        """二次、三次等重复后缀应该去除"""
        assert normalize_project_name("某项目二次招标") == normalize_project_name("某项目")
        assert normalize_project_name("某项目第三次采购") == normalize_project_name("某项目")
        assert normalize_project_name("某项目二次") == normalize_project_name("某项目")
        assert normalize_project_name("某项目第3次招标") == normalize_project_name("某项目")
        # 去除后应该相同
        assert normalize_project_name("某项目二次招标") == normalize_project_name("某项目招标公告")

    def test_business_suffix(self):
        """业务后缀应该去除"""
        assert normalize_project_name("某项目招标公告") == normalize_project_name("某项目")
        assert normalize_project_name("某项目中标结果") == normalize_project_name("某项目")
        assert normalize_project_name("某项目采购公告") == normalize_project_name("某项目")
        assert normalize_project_name("某项目结果公告") == normalize_project_name("某项目")
        assert normalize_project_name("某项目更正公告") == normalize_project_name("某项目")
        assert normalize_project_name("某项目变更公告") == normalize_project_name("某项目")
        assert normalize_project_name("某项目中标通知书") == normalize_project_name("某项目")

    def test_phase_suffix(self):
        """期段后缀去除后仍不同（期段本身是区分标志）"""
        n1 = normalize_project_name("某项目一期")
        n2 = normalize_project_name("某项目二期")
        n3 = normalize_project_name("某项目三期")
        assert n1 != n2 != n3
        # 但都包含基础名称
        assert "某项目" in n1
        assert "某项目" in n2

    def test_punctuation_and_space(self):
        """标点符号应该去除（转为空格）"""
        assert normalize_project_name("某 项目") == normalize_project_name("某项目")
        assert normalize_project_name("某-项目") == normalize_project_name("某项目")
        assert normalize_project_name("某：项目") == normalize_project_name("某项目")

    def test_empty(self):
        assert normalize_project_name("") == ""
        assert normalize_project_name("   ") == ""

    def test_lowercase(self):
        assert normalize_project_name("ABC项目") == "abc项目"


class TestExtractProjectNo:
    """extract_project_no 测试"""

    def test_招标编号_label(self):
        assert extract_project_no("某项目招标公告", "招标编号：CGZX-2024-1234") == "CGZX-2024-1234"
        assert extract_project_no("某项目", "招标编号：CGZX20241234") == "CGZX20241234"

    def test_项目编号_label(self):
        assert extract_project_no("某项目", "项目编号：XM2024-001") == "XM2024-001"

    def test_采购编号_label(self):
        assert extract_project_no("某项目", "采购编号：CG-2024-0001") == "CG-2024-0001"

    def test_standard_format(self):
        """标准格式 XX-YYYY-NNNN"""
        assert extract_project_no("某项目", "CGZX-2024-1234") == "CGZX-2024-1234"
        assert extract_project_no("某项目", "XM-2025-0001") == "XM-2025-0001"

    def test_bracket_format(self):
        """方括号格式"""
        assert extract_project_no("某项目", "[CGZX-2024-1234-AB]") == "CGZX-2024-1234-AB"
        assert extract_project_no("某项目", "[XM20240001]") == "XM20240001"

    def test_in_title(self):
        """标题中包含编号"""
        assert extract_project_no("某项目招标公告 CGZX-2024-1234", "") == "CGZX-2024-1234"

    def test_no_match(self):
        assert extract_project_no("某项目", "") is None
        assert extract_project_no("某项目", "这是一段普通描述文字") is None

    def test_priority(self):
        """应该返回第一个匹配到的编号"""
        text = "招标编号：CGZX-2024-0001，项目编号：XM-2024-0002"
        assert extract_project_no("某项目", text) == "CGZX-2024-0001"


class TestNormalizeProjectNo:
    """normalize_project_no 测试"""

    def test_basic(self):
        assert normalize_project_no("CGZX-2024-1234") == "CGZX20241234"
        assert normalize_project_no("cgzx-2024-1234") == "CGZX20241234"
        assert normalize_project_no("CGZX 2024 1234") == "CGZX20241234"

    def test_empty(self):
        assert normalize_project_no("") == ""
        assert normalize_project_no("   ") == ""


class TestMatchProject:
    """match_project 测试"""

    def test_no_match_empty_name(self):
        result = match_project(None, "", [])
        assert result is None

    def test_no_match_no_existing(self):
        result = match_project(None, "某项目", [])
        assert result is None

    def test_no_match_different_names(self):
        existing = [{"name": "项目A", "project_no": ""}, {"name": "项目B", "project_no": ""}]
        result = match_project(None, "项目C", existing)
        assert result is None

    def test_match_by_no(self):
        """编号完全一致 → 合并"""
        existing = [
            {"name": "项目A", "project_no": "CGZX-2024-1234"},
            {"name": "项目B", "project_no": "XM-2024-0001"},
        ]
        result = match_project("CGZX-2024-1234", "某项目", existing)
        assert result is not None
        assert result["name"] == "项目A"

    def test_match_by_no_different_formats(self):
        """编号格式不同但实际相同 → 应该匹配"""
        existing = [{"name": "项目A", "project_no": "CGZX20241234"}]
        result = match_project("CGZX-2024-1234", "某项目", existing)
        # 经过 normalize_project_no 比对应该能匹配
        assert result is not None
        assert result["name"] == "项目A"

    def test_match_by_normalized_name(self):
        """名称规范化后一致 → 合并"""
        existing = [
            {"name": "某项目招标公告", "project_no": ""},
            {"name": "另一个项目", "project_no": ""},
        ]
        result = match_project(None, "某项目中标结果", existing)
        assert result is not None
        assert result["name"] == "某项目招标公告"

    def test_match_priority_no_over_name(self):
        """编号匹配优先于名称匹配"""
        existing = [
            {"name": "项目A", "project_no": "CGZX-2024-1234"},
            {"name": "某项目", "project_no": ""},
        ]
        result = match_project("CGZX-2024-1234", "某项目", existing)
        assert result is not None
        assert result["name"] == "项目A"  # 编号匹配优先

    def test_match_with_repeat_suffix(self):
        """二次招标 vs 原项目 → 应该匹配"""
        existing = [{"name": "某项目", "project_no": ""}]
        result = match_project(None, "某项目二次招标", existing)
        assert result is not None
        assert result["name"] == "某项目"

    def test_match_with_business_suffix(self):
        """招标公告 vs 中标结果 → 应该匹配同一项目"""
        existing = [{"name": "某项目招标公告", "project_no": ""}]
        result = match_project(None, "某项目中标结果公告", existing)
        assert result is not None


class TestGetProjectKey:
    """get_project_key 测试"""

    def test_basic(self):
        key = get_project_key("某项目")
        assert key[0] == "某项目"
        assert key[1] is None

    def test_with_no(self):
        key = get_project_key("某项目", "CGZX-2024-1234")
        assert key[0] == "某项目"
        assert key[1] == "CGZX20241234"

    def test_consistency(self):
        """同一项目不同形式应生成相同 key"""
        key1 = get_project_key("某项目招标公告", "CGZX-2024-1234")
        key2 = get_project_key("某项目中标结果", "CGZX-2024-1234")
        assert key1 == key2

    def test_different_projects_different_keys(self):
        """不同项目不同 key"""
        key1 = get_project_key("项目A", "CGZX-2024-0001")
        key2 = get_project_key("项目B", "CGZX-2024-0002")
        assert key1 != key2
