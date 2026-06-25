"""fahcqmu API 路由单测 (F5)

端点:
- GET /api/fahcqmu/health
- GET /api/fahcqmu/stats
- GET /api/fahcqmu/projects
- GET /api/fahcqmu/project/{url}

策略: 用 in-memory SQLite 替代 PostgreSQL, 通过 monkey-patching 测试路由逻辑。
不测 SQL 本身 (那是 db.py 的责任, 由 test_db.py 覆盖)。
"""
import json
import sqlite3
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ──────────────────────────────────────────────────────
@pytest.fixture
def fake_db():
    """模拟 DB: 返回 _DictRow-like 行为."""
    db = MagicMock()

    # Health
    db._get_conn.return_value.execute.return_value.fetchone.return_value = {
        "cnt": 1667,
        "last": datetime(2026, 6, 25, 21, 0, 0),
    }
    return db


@pytest.fixture
def client(fake_db):
    """FastAPI TestClient + DB patch."""
    from fastapi.testclient import TestClient
    from web_server import app

    with patch("app.api.routes.fahcqmu.get_db", return_value=fake_db):
        with TestClient(app) as c:
            yield c


# ── Tests ─────────────────────────────────────────────────────────
def test_health_ok(client, fake_db):
    r = client.get("/api/fahcqmu/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["table"] == "projects_fahcqmu"
    assert data["total_rows"] == 1667


def test_health_error(client, fake_db):
    """DB 异常时返回 500."""
    fake_db._get_conn.return_value.execute.side_effect = Exception("DB down")
    r = client.get("/api/fahcqmu/health")
    assert r.status_code == 500
    data = r.json()
    assert data["status"] == "error"


def test_stats_basic(client, fake_db):
    """stats 端点: 总数 + by_org_unit + by_info_type + by_date + date_range."""
    # Mock 多次 execute 调用 (count, group by org, group by info, group by date, range)
    call_count = [0]

    def fake_execute(sql, params=None):
        m = MagicMock()
        idx = call_count[0]
        call_count[0] += 1
        if idx == 0:  # COUNT
            m.fetchone.return_value = {"cnt": 100}
        elif idx == 1:  # by org
            m.fetchall.return_value = [
                {"org_unit": "总务处", "cnt": 80},
                {"org_unit": "信息数据处", "cnt": 18},
                {"org_unit": "其他", "cnt": 2},
            ]
        elif idx == 2:  # by info_type
            m.fetchall.return_value = [
                {"info_type": "jggs", "cnt": 50},
                {"info_type": "cggg", "cnt": 30},
            ]
        elif idx == 3:  # by date
            m.fetchall.return_value = [
                {"publish_date": __import__("datetime").date(2026, 6, 25), "cnt": 5},
            ]
        elif idx == 4:  # range
            m.fetchone.return_value = {
                "start": __import__("datetime").date(2025, 1, 1),
                "end": __import__("datetime").date(2026, 6, 25),
            }
        return m

    fake_db._get_conn.return_value.execute.side_effect = fake_execute

    r = client.get("/api/fahcqmu/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 100
    assert data["by_org_unit"] == {"总务处": 80, "信息数据处": 18, "其他": 2}
    assert data["by_info_type"] == {"jggs": 50, "cggg": 30}
    assert len(data["by_date"]) == 1
    assert data["date_range"]["start"] == "2025-01-01"
    assert data["date_range"]["end"] == "2026-06-25"


def test_projects_list_pagination(client, fake_db):
    """列表分页 + 关键词过滤."""
    call_count = [0]

    def fake_execute(sql, params=None):
        m = MagicMock()
        idx = call_count[0]
        call_count[0] += 1
        if idx == 0:  # COUNT
            m.fetchone.return_value = {"cnt": 50}
        elif idx == 1:  # SELECT
            m.fetchall.return_value = [
                {
                    "id": 1, "url": "https://www.fahcqmu.cn/test/1",
                    "title": "测试项目", "category": "医院采购",
                    "info_type": "cggg", "business_type": "医院采购",
                    "org_unit": "总务处", "publish_date": __import__("datetime").date(2026, 6, 25),
                    "content_preview": "测试摘要", "full_content": "测试详情",
                    "budget": "100万", "bid_amount": "", "region": "重庆",
                    "industry": "医疗", "tender_type": "公开招标",
                    "project_no": "TEST-001", "contact_name": "张三",
                    "contact_phone": "023-12345678", "contact_email": "zhangsan@test.cn",
                    "attachments_count": 0,
                    "scraped_at": datetime(2026, 6, 25, 22, 0, 0),
                    "scraped_by": "tender-scraper v3.2 fahcqmu",
                }
            ]
        return m

    fake_db._get_conn.return_value.execute.side_effect = fake_execute

    r = client.get("/api/fahcqmu/projects?page=1&page_size=10&keyword=测试")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 50
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert data["has_more"] is True
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "测试项目"
    assert data["items"][0]["org_unit"] == "总务处"
    # datetime 应该被 ISO 化
    assert "2026-06-25" in data["items"][0]["scraped_at"]


def test_project_detail_found(client, fake_db):
    """详情找到."""
    fake_db._get_conn.return_value.execute.return_value.fetchone.return_value = {
        "id": 1, "url": "https://www.fahcqmu.cn/test/1", "title": "详情测试",
        "org_unit": "信息数据处", "info_type": "dygg", "publish_date": None,
        "scraped_at": datetime(2026, 6, 25, 21, 0, 0),
    }
    r = client.get("/api/fahcqmu/project/https://www.fahcqmu.cn/test/1")
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "详情测试"


def test_project_detail_not_found(client, fake_db):
    """详情未找到 → 404."""
    fake_db._get_conn.return_value.execute.return_value.fetchone.return_value = None
    r = client.get("/api/fahcqmu/project/https://www.fahcqmu.cn/missing")
    assert r.status_code == 404
    assert r.json()["error"] == "not found"


def test_projects_list_no_filter(client, fake_db):
    """无过滤参数也能跑通 (空条件)."""
    call_count = [0]

    def fake_execute(sql, params=None):
        m = MagicMock()
        idx = call_count[0]
        call_count[0] += 1
        if idx == 0:
            m.fetchone.return_value = {"cnt": 0}
        elif idx == 1:
            m.fetchall.return_value = []
        return m

    fake_db._get_conn.return_value.execute.side_effect = fake_execute

    r = client.get("/api/fahcqmu/projects")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["items"] == []
    assert data["has_more"] is False


def test_projects_list_order_by(client, fake_db):
    """order_by 参数可切换."""
    call_count = [0]

    def fake_execute(sql, params=None):
        m = MagicMock()
        idx = call_count[0]
        call_count[0] += 1
        if idx == 0:
            m.fetchone.return_value = {"cnt": 0}
        elif idx == 1:
            m.fetchall.return_value = []
        return m

    fake_db._get_conn.return_value.execute.side_effect = fake_execute

    r = client.get("/api/fahcqmu/projects?order_by=publish_date_asc")
    assert r.status_code == 200
    # 验证 SQL 中含 ASC
    second_call_sql = fake_db._get_conn.return_value.execute.call_args_list[1][0][0]
    assert "ASC" in second_call_sql


def test_stats_with_org_filter(client, fake_db):
    """stats 加 org_unit 过滤参数."""
    call_count = [0]

    def fake_execute(sql, params=None):
        m = MagicMock()
        idx = call_count[0]
        call_count[0] += 1
        if idx == 0:
            m.fetchone.return_value = {"cnt": 80}
        elif idx == 1:
            m.fetchall.return_value = [{"org_unit": "总务处", "cnt": 80}]
        elif idx == 2:
            m.fetchall.return_value = [{"info_type": "jggs", "cnt": 50}]
        elif idx == 3:
            m.fetchall.return_value = []
        elif idx == 4:
            m.fetchone.return_value = {"start": None, "end": None}
        return m

    fake_db._get_conn.return_value.execute.side_effect = fake_execute

    r = client.get("/api/fahcqmu/stats?org_unit=总务处")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 80
    # 验证参数传递
    first_call_params = fake_db._get_conn.return_value.execute.call_args_list[0][0][1]
    assert "总务处" in first_call_params
