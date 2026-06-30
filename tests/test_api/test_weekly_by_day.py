#!/usr/bin/env python3
"""本周采集 Mon-Sun 7 日拆分 单测 (2026-06-30)

User feedback: 'data 页面 本周采集 统计周一至周天 采集项目数量 而非采集时间'
Fix: 新增 _compute_weekly_by_day(projects, week_start_date) helper
     返回 [Mon, Tue, Wed, Thu, Fri, Sat, Sun] 7 元素数组 (项目数 / 日)
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


class TestComputeWeeklyByDay:
    """测试 _compute_weekly_by_day 函数"""

    def setup_method(self):
        """每个测试前重置模块避免缓存"""
        if "app.api.routes.projects" in sys.modules:
            del sys.modules["app.api.routes.projects"]
        from app.api.routes.projects import _compute_weekly_by_day
        self.compute = _compute_weekly_by_day

    def test_basic_distribution(self):
        """基本 7 天分布: 周一 2, 周二 3, 其他 0, 周日 1"""
        projects = [
            {"scraped_at": "2026-06-29 10:00:00"},  # Mon
            {"scraped_at": "2026-06-29 11:00:00"},  # Mon
            {"scraped_at": "2026-06-30 09:00:00"},  # Tue
            {"scraped_at": "2026-06-30 09:30:00"},  # Tue
            {"scraped_at": "2026-06-30 10:00:00"},  # Tue
            {"scraped_at": "2026-07-05 12:00:00"},  # Sun
        ]
        ws = date(2026, 6, 29)  # Mon
        result = self.compute(projects, ws)
        assert result == [2, 3, 0, 0, 0, 0, 1], f"got {result}"

    def test_empty_list_returns_zeros(self):
        """空 projects → 7 个 0"""
        ws = date(2026, 6, 29)
        result = self.compute([], ws)
        assert result == [0, 0, 0, 0, 0, 0, 0]

    def test_none_and_empty_scraped_at_ignored(self):
        """scraped_at 为 None 或空字符串应忽略"""
        projects = [
            {"scraped_at": None},
            {"scraped_at": ""},
            {"scraped_at": "2026-06-29 12:00:00"},
        ]
        ws = date(2026, 6, 29)
        result = self.compute(projects, ws)
        assert result == [1, 0, 0, 0, 0, 0, 0]

    def test_time_boundary_date_only(self):
        """scraped_at 时间部分 (HH:MM:SS) 不影响日期归属"""
        projects = [
            {"scraped_at": "2026-07-01 23:59:59.999999"},  # Wed
            {"scraped_at": "2026-07-02 00:00:00.000001"},  # Thu
        ]
        ws = date(2026, 6, 29)
        result = self.compute(projects, ws)
        assert result == [0, 0, 1, 1, 0, 0, 0]

    def test_week_boundary_excludes_neighbours(self):
        """上周日 / 下周一不计入本周"""
        projects = [
            {"scraped_at": "2026-06-28 23:59:00"},  # Sun of last week
            {"scraped_at": "2026-07-06 00:00:00"},  # Mon of next week
            {"scraped_at": "2026-06-29 00:00:00"},  # Mon of this week
        ]
        ws = date(2026, 6, 29)
        result = self.compute(projects, ws)
        assert result == [1, 0, 0, 0, 0, 0, 0]

    def test_weekend_concentration(self):
        """项目集中在周末"""
        projects = [
            {"scraped_at": "2026-07-04 10:00:00"},  # Sat
            {"scraped_at": "2026-07-04 11:00:00"},  # Sat
            {"scraped_at": "2026-07-05 12:00:00"},  # Sun
        ]
        ws = date(2026, 6, 29)
        result = self.compute(projects, ws)
        assert result == [0, 0, 0, 0, 0, 2, 1]

    def test_returns_list_of_seven_ints(self):
        """返回值必须是长度 7 的整数列表"""
        ws = date(2026, 6, 29)
        result = self.compute([], ws)
        assert isinstance(result, list)
        assert len(result) == 7
        assert all(isinstance(x, int) for x in result)

    def test_iso_string_dates(self):
        """scraped_at 为 ISO 字符串 (2026-06-29) 也应工作"""
        projects = [
            {"scraped_at": "2026-06-29"},
            {"scraped_at": "2026-06-29T10:00:00"},
            {"scraped_at": "2026-06-29T15:30:45.123456"},
        ]
        ws = date(2026, 6, 29)
        result = self.compute(projects, ws)
        assert result == [3, 0, 0, 0, 0, 0, 0]


class TestStatsEndpointIntegration:
    """测试 /api/stats 端点返回 weekly_by_day / week_dates / weekday_today 字段

    注: 不测端点本身 (需 DB + auth mock, 复杂度高),
    而是直接验证 get_stats() 的输出 dict 结构 (绕过 HTTP 层)。
    """

    def setup_method(self):
        if "app.api.routes.projects" in sys.modules:
            del sys.modules["app.api.routes.projects"]

    def test_get_stats_returns_weekly_by_day_fields(self):
        """get_stats() 返回 dict 必含 weekly_by_day / week_dates / weekday_today"""
        from unittest.mock import patch, MagicMock

        fake_projects = [
            {"scraped_at": "2026-06-29 10:00:00", "keywords_matched": ""},
            {"scraped_at": "2026-06-30 09:00:00", "keywords_matched": ""},
        ]
        fake_settings = MagicMock()
        fake_settings.is_self_mode = True

        # patch get_stats 内部依赖
        with patch("app.api.routes.projects._load_projects", return_value=(fake_projects, 2)), \
             patch("app.api.routes.projects._get_last_run", return_value="2026-06-30 09:00:00"), \
             patch("app.api.routes.projects.get_current_user_id_required", return_value="admin"), \
             patch("app.api.routes.projects.get_db") as fake_get_db:
            from app.api.routes.projects import get_stats
            from starlette.requests import Request
            req = MagicMock(spec=Request)
            resp = get_stats(req)
            # JSONResponse → 拿 json 内容
            if hasattr(resp, "body"):
                import json
                body = json.loads(resp.body)
            else:
                body = resp  # dict

        # 关键字段存在
        assert "weekly_by_day" in body, f"Missing weekly_by_day in {list(body.keys())}"
        assert "week_dates" in body, f"Missing week_dates in {list(body.keys())}"
        assert "weekday_today" in body, f"Missing weekday_today in {list(body.keys())}"

        # 类型正确
        assert isinstance(body["weekly_by_day"], list)
        assert len(body["weekly_by_day"]) == 7
        assert all(isinstance(x, int) for x in body["weekly_by_day"])
        assert isinstance(body["week_dates"], list)
        assert len(body["week_dates"]) == 7
        assert isinstance(body["weekday_today"], int)
        assert 0 <= body["weekday_today"] <= 6

        # 既有字段仍存在 (向后兼容)
        assert "total" in body
        assert "today" in body
        assert "weekly_count" in body
        assert "last_run" in body

        # weekly_by_day 内容验证 (mock 数据: Mon=1, Tue=1)
        assert body["weekly_by_day"][0] == 1, f"Mon count: {body['weekly_by_day']}"
        assert body["weekly_by_day"][1] == 1, f"Tue count: {body['weekly_by_day']}"