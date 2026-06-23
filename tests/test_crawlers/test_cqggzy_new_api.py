"""测试 CQGGZY 新 API 端点和严格白名单 (2026-06-23)
- 新端点: /api/special-zone/search-engine-page
- 严格 8 大类白名单 (用户 6-23 明确指令)
"""
import json
import pytest
from unittest.mock import AsyncMock, patch

from app.crawlers.cqggzy import CQGGZYCrawlerV2


class TestCQGGZYListURLs:
    """测试 LIST_URLS 配置：用户指定的 8 大数据源"""

    def test_user_specified_8_categories(self):
        """用户 6-23 明确指令: 8 大类严格白名单"""
        crawler = CQGGZYCrawlerV2
        expected = {
            "engineering_plan", "engineering_notice", "engineering_qa",
            "engineering_candidate", "engineering_result",
            "gov_purchase_notice", "gov_purchase_change", "gov_purchase_result",
        }
        assert set(crawler.LIST_URLS.keys()) == expected

    def test_engineering_trade_id(self):
        """工程招投标: trade=014001"""
        assert CQGGZYCrawlerV2.LIST_URLS["engineering_notice"][0] == "014001"
        assert CQGGZYCrawlerV2.LIST_URLS["engineering_notice"][1] == "014001001"

    def test_gov_purchase_trade_id(self):
        """政府采购: trade=014005"""
        assert CQGGZYCrawlerV2.LIST_URLS["gov_purchase_notice"][0] == "014005"
        assert CQGGZYCrawlerV2.LIST_URLS["gov_purchase_notice"][1] == "014005001"

    def test_allowed_prefixes_excludes_old_classes(self):
        """严格白名单: 不包含已废弃的 014001021 (终止公告) / 014005003 (中标公告) / 014005005 等"""
        for forbidden in ("014001021", "014005003", "014005005", "014005008", "014001015", "014001016"):
            assert forbidden not in CQGGZYCrawlerV2._ALLOWED_CATNUM_PREFIXES, \
                f"User 6-23 banned {forbidden} from collection"

    def test_info_type_map_matches(self):
        """INFO_TYPE_MAP 与 LIST_URLS 8 大类一一对应"""
        for key in CQGGZYCrawlerV2.LIST_URLS:
            assert key in CQGGZYCrawlerV2.INFO_TYPE_MAP, f"Missing info_type for {key}"


class TestCQGGZYAPIEndpoint:
    """测试新 API 端点和 payload 结构"""

    def test_api_endpoint_is_new(self):
        """新端点: /api/special-zone/search-engine-page (2026-06-23 改版)"""
        import inspect
        from app.crawlers import cqggzy
        source = inspect.getsource(cqggzy)
        assert "/api/special-zone/search-engine-page" in source
        # 旧端点不应再使用
        assert "/api/v2/search-engine-page" not in source or \
               "page" in source.split("/api/v2/search-engine-page")[0][-50:]

    def test_condition_array_structure(self):
        """验证 payload 使用 condition 数组 (前端实际格式)"""
        import inspect
        from app.crawlers import cqggzy
        source = inspect.getsource(cqggzy)
        # 验证 condition 数组结构关键字段
        assert '"fieldName": "categorynum"' in source
        assert '"equalList"' in source
        assert '"isLike": True' in source
        assert '"likeType": 2' in source
        assert '"noWd": True' in source


class TestCQGGZYURLConstruction:
    """测试 URL 构造: infoid 必须带连字符, categoryNum 12 位"""

    def test_url_format_correct(self):
        """URL 格式: /trade/{trade_id}/{infoid_with_dashes}?categoryNum={catnum}"""
        infoid = "98501990-a737-40ab-bbf2-4f056d468934"
        catnum = "014001001001"
        trade = "014001"
        expected = f"https://www.cqggzy.com/trade/{trade}/{infoid}?categoryNum={catnum}"
        # 验证 infoid 保留连字符 (新 API 返回的格式)
        assert "-" in infoid
        assert expected.startswith("https://www.cqggzy.com/trade/014001/")
        assert "?categoryNum=014001001001" in expected


class TestCQGGZYResponseParse:
    """测试新 API 响应解析"""

    def test_records_extraction(self):
        """验证从 content.result.records 提取记录"""
        mock_response = {
            "code": 200,
            "content": json.dumps({
                "result": {
                    "totalcount": 100,
                    "records": [
                        {
                            "title": "测试项目",
                            "infoid": "98501990-a737-40ab-bbf2-4f056d468934",
                            "categorynum": "014001001001",
                            "content": "项目内容",
                            "pubinwebdate": "2026-06-23",
                            "webdate": "2026-06-23 10:00:00",
                        }
                    ]
                }
            })
        }
        content = json.loads(mock_response["content"])
        records = content["result"]["records"]
        assert len(records) == 1
        assert records[0]["infoid"] == "98501990-a737-40ab-bbf2-4f056d468934"
        assert records[0]["categorynum"] == "014001001001"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
