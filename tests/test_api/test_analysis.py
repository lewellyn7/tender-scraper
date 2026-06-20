"""
test_analysis.py — analysis API 工具函数 + SQL 单测

覆盖:
- _quarter_range 季度日期计算
- _resolve_period 参数解析
- _category_filter category → info_type SQL 转换
- /api/analysis/bid-rank project_type 参数 (2026-06-20)
- /api/analysis/bid-rank-by-type 按类型分组 (2026-06-20)
"""
import sys
import os
from datetime import date
from unittest.mock import MagicMock, patch

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

# ─── bid-rank project_type 参数 (2026-06-20 新增) ────────────────────────────

class TestBidRankProjectTypeFilter:
    """验证 project_type 参数注入 SQL 的逻辑 — 用 FastAPI TestClient."""

    def test_bid_rank_带project_type(self):
        """project_type 参数被注入到 SQL (不实际连库, 验证 SQL 构造)."""
        from fastapi.testclient import TestClient
        from unittest.mock import patch, MagicMock

        # 模拟 DB 返回
        mock_rows = [
            ("重庆智信", 5, 1200000.0, 240000.0, None, None, None, None, 5),
        ]
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = mock_rows
        mock_cursor.close = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("app.api.routes.analysis.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db._get_conn.return_value = mock_conn
            mock_get_db.return_value = mock_db

            from web_server import app
            client = TestClient(app)
            res = client.get(
                "/api/analysis/bid-rank?category=政府采购&period=quarter&year=2026&quarter=2"
                "&project_type=智能化&sort_by=amount&limit=10"
            )
            # 200 表示路由可达; mock 不影响路由层
            assert res.status_code == 200, res.text
            data = res.json()
            assert data["project_type"] == "智能化"
            assert data["sort_by"] == "amount"
            assert data["total_winners"] == 1

    def test_bid_rank_无project_type_不过滤(self):
        """不传 project_type → 不过滤, 响应里 project_type=null."""
        with patch("app.api.routes.analysis.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = []
            mock_cursor.close = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_db._get_conn.return_value = mock_conn
            mock_get_db.return_value = mock_db

            from web_server import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            res = client.get(
                "/api/analysis/bid-rank?category=政府采购&period=quarter&year=2026&quarter=2"
            )
            assert res.status_code == 200
            assert res.json()["project_type"] is None


class TestBidRankByTypeEndpoint:
    """验证 /api/analysis/bid-rank-by-type 端点返回结构."""

    def test_by_type_返回所有类型(self):
        """按类型分组的 SQL 应返回 by_type 字典 + type_summary 列表."""
        # 多类型 + 多 winner 模拟数据
        mock_rows = [
            # (project_type, winner_name, pc, total, avg_score, first, last)
            ("智能化", "智信科技", 3, 1200000.0, 95.5, None, None),
            ("智能化", "智慧科技", 1, 500000.0, None, None, None),
            ("老旧小区改造", "建工集团", 5, 5000000.0, 88.0, None, None),
            ("其他", "其他公司", 2, 100000.0, None, None, None),
        ]
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = mock_rows
        mock_cursor.close = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("app.api.routes.analysis.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db._get_conn.return_value = mock_conn
            mock_get_db.return_value = mock_db

            from web_server import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            res = client.get(
                "/api/analysis/bid-rank-by-type?category=政府采购&period=quarter&year=2026&quarter=2"
                "&sort_by=amount&limit=10"
            )
            assert res.status_code == 200, res.text
            data = res.json()

            # 顶层字段
            assert data["sort_by"] == "amount"
            assert data["limit"] == 10
            assert "by_type" in data
            assert "type_summary" in data

            # by_type 应包含 3 个类型
            by_type = data["by_type"]
            assert "智能化" in by_type
            assert "老旧小区改造" in by_type
            assert "其他" in by_type

            # 智能化组 Top 1 应是智信科技
            assert by_type["智能化"]["rankings"][0]["winner_name"] == "智信科技"
            assert by_type["智能化"]["rankings"][0]["rank"] == 1
            assert by_type["智能化"]["rankings"][1]["winner_name"] == "智慧科技"
            assert by_type["智能化"]["rankings"][1]["rank"] == 2

            # 老旧小区改造组 Top 1
            assert by_type["老旧小区改造"]["rankings"][0]["winner_name"] == "建工集团"

            # type_summary 按 sort_by 字段降序
            summary = data["type_summary"]
            # 老旧小区改造 5000000 > 智能化 1700000 > 其他 100000
            assert summary[0]["type"] == "老旧小区改造"
            assert summary[1]["type"] == "智能化"
            assert summary[2]["type"] == "其他"
            # 字段完整性
            for item in summary:
                assert "total_projects" in item
                assert "total_amount" in item
                assert "type" in item

    def test_by_type_sort_by_count(self):
        """sort_by=count 按项目数排序."""
        mock_rows = [
            ("智能化", "智信科技", 10, 1000000.0, None, None, None),
            ("老旧小区改造", "建工集团", 5, 5000000.0, None, None, None),
        ]
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = mock_rows
        mock_cursor.close = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("app.api.routes.analysis.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db._get_conn.return_value = mock_conn
            mock_get_db.return_value = mock_db

            from web_server import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            res = client.get(
                "/api/analysis/bid-rank-by-type?category=政府采购&period=quarter&year=2026&quarter=2"
                "&sort_by=count&limit=10"
            )
            assert res.status_code == 200
            data = res.json()
            # sort_by=count → 智能化 10 项目 > 老旧 5
            assert data["type_summary"][0]["type"] == "智能化"
            assert data["type_summary"][1]["type"] == "老旧小区改造"

    def test_by_type_period_400(self):
        """period 缺参数应 400."""
        from web_server import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        res = client.get("/api/analysis/bid-rank-by-type?category=政府采购")
        assert res.status_code == 400
        assert "quarter" in res.json()["error"]


# ─── project_types 多选 (2026-06-20 14:00 新增) ──────────────────────────────────

class TestProjectTypesMultiSelect:
    """多值 project_types 逗号分隔参数 + && 操作符 SQL."""

    def test_多值逗号分隔(self):
        """project_types=智能化,老旧小区改造 应注入 && ARRAY[...] 语义."""
        with patch("app.api.routes.analysis.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = []
            mock_cursor.close = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_db._get_conn.return_value = mock_conn
            mock_get_db.return_value = mock_db

            from web_server import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            res = client.get(
                "/api/analysis/bid-rank?category=政府采购&period=quarter&year=2026&quarter=2"
                "&project_types=智能化,老旧小区改造"
            )
            assert res.status_code == 200, res.text
            data = res.json()
            # 响应里 project_types 应是拆分后的列表
            assert data["project_types"] == ["智能化", "老旧小区改造"]
            assert data["project_type"] is None  # 单值字段 null (兼容)

    def test_向后兼容_单值project_type(self):
        """仅传 project_type=智能化 应仍可用 (单值路径)."""
        with patch("app.api.routes.analysis.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = []
            mock_cursor.close = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_db._get_conn.return_value = mock_conn
            mock_get_db.return_value = mock_db

            from web_server import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            res = client.get(
                "/api/analysis/bid-rank?category=政府采购&period=quarter&year=2026&quarter=2"
                "&project_type=智能化"
            )
            assert res.status_code == 200
            data = res.json()
            # project_types 也回填为 ['智能化'] (规范化)
            assert data["project_types"] == ["智能化"]
            assert data["project_type"] == "智能化"

    def test_都不传(self):
        """不传任何 type 参数 → 都不过滤."""
        with patch("app.api.routes.analysis.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = []
            mock_cursor.close = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_db._get_conn.return_value = mock_conn
            mock_get_db.return_value = mock_db

            from web_server import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            res = client.get(
                "/api/analysis/bid-rank?category=政府采购&period=quarter&year=2026&quarter=2"
            )
            assert res.status_code == 200
            data = res.json()
            assert data["project_types"] is None
            assert data["project_type"] is None

    def test_空字符串忽略(self):
        """project_types=  (空) 应被忽略."""
        with patch("app.api.routes.analysis.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = []
            mock_cursor.close = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_db._get_conn.return_value = mock_conn
            mock_get_db.return_value = mock_db

            from web_server import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            res = client.get(
                "/api/analysis/bid-rank?category=政府采购&period=quarter&year=2026&quarter=2"
                "&project_types="
            )
            assert res.status_code == 200
            data = res.json()
            # 全部空 token → 不过滤
            assert data["project_types"] is None

    def test_优先级_project_types_优先(self):
        """同时传 project_type + project_types 时, project_types 优先."""
        with patch("app.api.routes.analysis.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = []
            mock_cursor.close = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_db._get_conn.return_value = mock_conn
            mock_get_db.return_value = mock_db

            from web_server import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            res = client.get(
                "/api/analysis/bid-rank?category=政府采购&period=quarter&year=2026&quarter=2"
                "&project_type=智能化&project_types=老旧小区改造,零星维修"
            )
            assert res.status_code == 200
            data = res.json()
            # project_types 多值优先
            assert data["project_types"] == ["老旧小区改造", "零星维修"]
            # project_type 单值仍回显 (兼容)
            assert data["project_type"] == "智能化"
