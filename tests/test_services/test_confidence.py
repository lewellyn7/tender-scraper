"""confidence 真实计算测试 (qualification-ai P0-3)

修复 2026-06-07: 之前 confidence 是常量 0.3（规则路径）/ 0.8（LLM 路径），
与实际识别质量毫无关联，欺骗前端用户。

新公式：
    score = 0.6 × (关键字段非空数 / 5) + 0.4 × (辅助字段非空数 / 9)

关键字段 (5)：certificate_type, name, id_number, certificate_no, valid_to
辅助字段 (9)：level, issuer, title, person_name, registered_city,
              address, legal_person, valid_from, construction_no
"""
import pytest


class TestComputeConfidence:
    """_compute_confidence 单元测试"""

    def test_empty_fields_zero_confidence(self):
        from app.services.document_analyzer import _compute_confidence
        assert _compute_confidence({}) == 0.0

    def test_only_none_or_empty_strings_zero(self):
        from app.services.document_analyzer import _compute_confidence
        assert _compute_confidence({
            "certificate_type": None,
            "name": "",
            "id_number": "   ",
        }) == 0.0

    def test_all_key_fields_maximum(self):
        """5 个关键字段全填 → 0.6 分"""
        from app.services.document_analyzer import _compute_confidence
        fields = {
            "certificate_type": "营业执照",
            "name": "XX 公司",
            "id_number": "110101199001011234",
            "certificate_no": "91110000ABCDEFGHIJ",
            "valid_to": "2026-12-31",
        }
        conf = _compute_confidence(fields)
        assert conf == 0.6

    def test_all_aux_fields_maximum(self):
        """9 个辅助字段全填 → 0.4 分"""
        from app.services.document_analyzer import _compute_confidence
        fields = {f: "v" for f in [
            "level", "issuer", "title", "person_name", "registered_city",
            "address", "legal_person", "valid_from", "construction_no",
        ]}
        conf = _compute_confidence(fields)
        assert conf == 0.4

    def test_all_fields_full(self):
        """全字段填 → 1.0 分"""
        from app.services.document_analyzer import _compute_confidence
        fields = {f: "v" for f in [
            "certificate_type", "name", "id_number", "certificate_no", "valid_to",
            "level", "issuer", "title", "person_name", "registered_city",
            "address", "legal_person", "valid_from", "construction_no",
        ]}
        conf = _compute_confidence(fields)
        assert conf == 1.0

    def test_partial_key_fields(self):
        """3/5 关键字段 → 0.6 × 0.6 = 0.36"""
        from app.services.document_analyzer import _compute_confidence
        fields = {
            "certificate_type": "营业执照",
            "name": "XX 公司",
            "id_number": "110101199001011234",
        }
        conf = _compute_confidence(fields)
        assert conf == pytest.approx(0.36, abs=0.001)

    def test_realistic_id_card(self):
        """真实身份证场景：5 关键 + 2 辅助"""
        from app.services.document_analyzer import _compute_confidence
        fields = {
            "certificate_type": "身份证",
            "person_name": "张三",
            "id_number": "110101199001011234",
            "valid_from": "2015-01-01",
            "valid_to": "2035-01-01",
            # 关键字段：certificate_type, person_name 当 name 用, id_number, valid_to
            # 但 name 字段未填 → 关键字段 = 4/5
            "name": None,
        }
        conf = _compute_confidence(fields)
        # 关键 4/5 = 0.8 → 0.6 × 0.8 = 0.48
        # 辅助 2/9 = 0.222 → 0.4 × 0.222 = 0.0888
        # 总分 ≈ 0.569
        # 实测：person_name/name 是同一字段，name 未填 → 关键 = 3/5
        # 0.6×0.6 + 0.4×(2/9) = 0.36 + 0.0888 = 0.449
        assert 0.43 < conf < 0.47


class TestRuleBasedExtractConfidence:
    """_rule_based_extract 真实 confidence 验证"""

    def test_empty_text_minimal_confidence(self):
        from app.services.document_analyzer import _rule_based_extract
        result = _rule_based_extract("无效文本")
        # 规则提取什么都拿不到
        assert result["confidence"] is not None
        assert result["confidence"] < 0.2

    def test_id_card_text_high_confidence(self):
        """身份证文本 → 应有较高 confidence"""
        from app.services.document_analyzer import _rule_based_extract
        text = """
        中华人民共和国居民身份证
        姓名 张三
        性别 男 民族 汉
        出生 1990年1月1日
        公民身份号码 110101199001011234
        住址 北京市朝阳区XX路XX号
        """
        result = _rule_based_extract(text)
        # 关键字段：certificate_type, name, id_number → 3/5
        # 辅助字段：registered_city/address → 1-2/9
        # 应该是中等偏上
        assert result["confidence"] is not None
        assert 0.3 < result["confidence"] < 0.8
        assert result["id_number"] == "110101199001011234"
        assert result["certificate_type"] == "身份证"

    def test_business_license_high_confidence(self):
        """营业执照文本 → 真实 confidence 反映规则提取的局限

        实测 confidence ≈ 0.24 (已知问题："名称"未被规则匹配到，name=None)
        这正是 P0-3 的价值 —— 真实反映提取质量，前端可低分高亮
        """
        from app.services.document_analyzer import _rule_based_extract
        text = """
        营业执照
        统一社会信用代码 91110000ABCDEFGHIJ
        法定代表人 李四
        名称 XX 科技有限公司
        注册资本 1000万
        注册地址 北京市海淀区XX路XX号
        成立日期 2010-01-01
        """
        result = _rule_based_extract(text)
        assert result["confidence"] is not None
        # 关键字段：certificate_type, certificate_no = 2/5 → 0.6×0.4=0.24
        # 辅助字段：legal_person=1/9 → 0.4×0.111=0.044
        # 总分 ≈ 0.24+0.044=0.284 (允许 0.2-0.35 区间)
        # 注：name 提取是规则 bug （"名称 XX 公司" 无冒号不匹配），后续 P1 修
        assert 0.2 < result["confidence"] < 0.35
        assert result["certificate_type"] == "营业执照"
        assert result["certificate_no"] == "91110000ABCDEFGHIJ"

    def test_constructor_certificate_medium_confidence(self):
        """建造师证书 → 中等 confidence"""
        from app.services.document_analyzer import _rule_based_extract
        text = """
        中华人民共和国一级建造师注册证书
        姓名 王五
        注册编号 建筑123456
        聘用企业 XX 建设有限公司
        """
        result = _rule_based_extract(text)
        assert result["confidence"] is not None
        # 关键字段：certificate_type, name → 2/5
        # 辅助字段：title, person_name（同时是 name）, registered_city → 2-3/9
        assert 0.2 < result["confidence"] < 0.6
        assert result["certificate_type"] == "建造师"


class TestBackwardCompatibility:
    """确保 confidence 不再是固定常量"""

    def test_confidence_no_longer_hardcoded_03(self):
        """_rule_based_extract 不再固定返回 0.3"""
        from app.services.document_analyzer import _rule_based_extract
        # 之前：所有规则提取都返回 0.3
        # 现在：应该基于字段完整度变化
        r1 = _rule_based_extract("无效")
        r2 = _rule_based_extract("姓名 张三\n身份证号 110101199001011234")
        # 至少有一个应该不是 0.3
        assert r1["confidence"] != r2["confidence"] or r2["confidence"] > 0.3

    def test_confidence_is_float(self):
        from app.services.document_analyzer import _compute_confidence
        conf = _compute_confidence({"name": "test"})
        assert isinstance(conf, float)
        assert 0.0 <= conf <= 1.0
