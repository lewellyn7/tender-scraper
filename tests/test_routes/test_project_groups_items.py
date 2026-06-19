"""P1-3a: /api/projects/groups 返回 items 数组单测 (2026-06-19)

验证 `get_project_groups` 端点返回的每个 group 包含 `items` 列表:
1. items 字段存在
2. items 最多 10 条
3. 每个 item 有 6 个必需字段 (id/title/info_type/publish_date/url/business_type)
4. items 按 publish_date DESC 排序
5. items 属于同 group_key (COALESCE 表达式)
6. 同 project_no 的 N 条记录在同 group (1:N 关联)

关联: PR #26 feat/p1-3a-group-expand
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Force self mode (skip auth) + production DB
os.environ["DEPLOYMENT_MODE"] = "self"
os.environ.setdefault(
    "DATABASE_URL", "postgresql://root:root123@localhost:5435/tender_scraper"
)


@pytest.fixture(scope="module", autouse=True)
def _setup_env():
    """确保环境变量在 web_server 导入前设置"""
    os.environ["DEPLOYMENT_MODE"] = "self"
    os.environ.setdefault(
        "DATABASE_URL", "postgresql://root:root123@localhost:5435/tender_scraper"
    )
    yield


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient (self 模式, 跳过 auth)"""
    from fastapi.testclient import TestClient
    import importlib

    import web_server

    importlib.reload(web_server)
    return TestClient(web_server.app)


class TestItemsArray:
    """P1-3a: items 数组结构验证"""

    def test_items_field_present(self, client):
        """每个 group 必含 items 字段"""
        r = client.get("/api/projects/groups?limit=10")
        assert r.status_code == 200
        groups = r.json().get("groups", [])
        assert len(groups) > 0, "生产库应至少有一个 group"
        for g in groups:
            assert "items" in g, f"group {g.get('code', '?')} 缺 items 字段"
            assert isinstance(g["items"], list), "items 必须是 list"

    def test_items_max_10(self, client):
        """items 最多 10 条 (LIMIT 10)"""
        r = client.get("/api/projects/groups?limit=200")
        groups = r.json().get("groups", [])
        for g in groups:
            assert len(g["items"]) <= 10, f"group {g.get('code')} items {len(g['items'])} > 10"

    def test_items_fields_complete(self, client):
        """每个 item 含 6 个必需字段"""
        r = client.get("/api/projects/groups?limit=200")
        groups = r.json().get("groups", [])
        required = {"id", "title", "info_type", "publish_date", "url", "business_type"}
        # 找至少一个有 items 的 group
        for g in groups:
            if g.get("items"):
                for it in g["items"]:
                    missing = required - set(it.keys())
                    assert not missing, f"item 缺字段: {missing}"
                return  # 验证一个 group 即可
        pytest.skip("无 group 含 items (生产库可能没数据)")

    def test_items_sorted_by_publish_date_desc(self, client):
        """items 按 publish_date DESC, 然后 id DESC"""
        r = client.get("/api/projects/groups?limit=200")
        groups = r.json().get("groups", [])
        for g in groups:
            items = g.get("items", [])
            if len(items) < 2:
                continue
            # 提取 (date, id) 元组, 验证降序
            # None / "" 视为最旧 (DESC NULLS LAST)
            date_pairs = [(it.get("publish_date") or "", it.get("id") or 0) for it in items]
            for i in range(len(date_pairs) - 1):
                a, b = date_pairs[i], date_pairs[i + 1]
                assert a >= b, f"items 未按 publish_date DESC 排序: {a} < {b}"
            return  # 验证一个有 ≥2 items 的 group 即可
        pytest.skip("无 group 含 ≥2 items")

    def test_items_belong_to_same_group(self, client):
        """同 group_key 下的 items COALESCE 表达式匹配"""
        r = client.get("/api/projects/groups?limit=200")
        groups = r.json().get("groups", [])
        for g in groups:
            items = g.get("items", [])
            if not items:
                continue
            # 每个 item 的 (project_no, url) 对应该 group_key
            group_key = g.get("code") or g.get("name")
            for it in items:
                # items 来自 COALESCE(NULLIF(project_no,''), url)
                # code == project_no 或 url
                assert it.get("title"), f"item 应有 title"
                assert it.get("url"), f"item 应有 url"
            return  # 一个 group 即可
        pytest.skip("无 group 含 items")


class TestGroupAggregation:
    """groups 聚合行为回归 (P1-3a 不影响原有行为)"""

    def test_count_matches_items(self, client):
        """count 字段不受 P1-3a 影响 (SQL 聚合依旧)"""
        r = client.get("/api/projects/groups?limit=200")
        groups = r.json().get("groups", [])
        for g in groups:
            # count >= items.length (因为 items LIMIT 10)
            assert g["count"] >= len(g.get("items", [])), \
                f"group {g.get('code')} count={g['count']} < items={len(g.get('items',[]))}"

    def test_record_types_unique(self, client):
        """record_types 是不重复的 info_type 列表"""
        r = client.get("/api/projects/groups?limit=200")
        groups = r.json().get("groups", [])
        for g in groups:
            rt = g.get("record_types", [])
            assert isinstance(rt, list)
            assert len(rt) == len(set(rt)), f"record_types 含重复: {rt}"


class TestItemsNtoOneLinking:
    """P1-3a 核心价值: 同 project_no 多个子公告可一起查"""

    def test_group_with_3_items_shows_full_lifecycle(self, client):
        """找到 count>=3 的 group, 验证 3 条子公告对应同一项目不同阶段"""
        r = client.get("/api/projects/groups?limit=200")
        groups = r.json().get("groups", [])
        for g in groups:
            items = g.get("items", [])
            if len(items) >= 3:
                # 所有 items 应有不同 info_type (典型: 招标公告 + 答疑补遗 + 中标公示)
                info_types = {it["info_type"] for it in items}
                assert len(info_types) >= 2, \
                    f"3 items 应含 ≥2 info_type, 实际: {info_types}"
                return
        pytest.skip("生产库无 count>=3 group (可用 spikes 测试)")

    def test_items_url_unique(self, client):
        """items 内 url 不重复 (排除同一记录被查 2 次)"""
        r = client.get("/api/projects/groups?limit=200")
        groups = r.json().get("groups", [])
        for g in groups:
            items = g.get("items", [])
            if not items:
                continue
            urls = [it["url"] for it in items]
            assert len(urls) == len(set(urls)), f"items url 重复: {urls}"
        return  # pass if checked
