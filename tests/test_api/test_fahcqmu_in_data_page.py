"""data 页加 fahcqmu 类目集成测试 (PR #43: feat/add-fahcqmu-to-data-page)

覆盖:
- _infer_business_type 识别 fahcqmu.cn URL → "医院采购"
- _load_projects 从 projects_fahcqmu 表加载
- _load_projects 后 fahcqmu 行的 business_type 字段被填充
- /api/projects category 过滤逻辑 (含 business_type 匹配)
"""
import sys
from datetime import datetime, date
from unittest.mock import MagicMock, patch

import pytest


# ── _infer_business_type 单元测试 ─────────────────────────────────
class TestInferBusinessType:
    """测试 URL → business_type 推理逻辑"""

    def setup_method(self):
        """每个测试前重置模块避免缓存"""
        if "app.api.routes.projects" in sys.modules:
            del sys.modules["app.api.routes.projects"]
        from app.api.routes.projects import _infer_business_type
        self.infer = _infer_business_type

    def test_fahcqmu_url_returns_yiyuancaigou(self):
        """fahcqmu.cn URL → 医院采购 (核心修复)"""
        urls = [
            "https://www.fahcqmu.cn/gw_yygg_zbgg_cgglczb2_cgxx_cggg/010100800040064.html",
            "https://fahcqmu.cn/abc",
            "https://anything.fahcqmu.cn/x",
        ]
        for url in urls:
            assert self.infer(url) == "医院采购", f"Failed for {url}"

    def test_caigou_url_returns_zhengfu(self):
        """014005 / order → 政府采购"""
        assert self.infer("https://www.ccgp.gov.cn/014005/order/abc") == "政府采购"
        assert self.infer("https://example.com/order/123") == "政府采购"

    def test_zhaobiao_url_returns_gongcheng(self):
        """014001 / bidding → 工程招投标"""
        assert self.infer("https://www.cqggzy.com/014001/bidding/abc") == "工程招投标"

    def test_title_fallback(self):
        """无 URL 模式匹配时按 title 关键词 fallback"""
        assert self.infer("https://unknown.com/x", title="某采购公告") == "政府采购"
        assert self.infer("https://unknown.com/x", title="某招标项目") == "工程招投标"

    def test_default_returns_zhengfu(self):
        """无任何匹配时默认 政府采购 (历史行为)"""
        assert self.infer("https://unknown.com/xyz", title="其他项目") == "政府采购"

    def test_priority_fahcqmu_over_caigou_keyword(self):
        """fahcqmu URL 优先于 title 关键词 (即使 title 含"采购")"""
        result = self.infer(
            "https://www.fahcqmu.cn/gw_yygg_zbgg_cgglczb2_cgxx_cggg/010100800040064.html",
            title="重庆医科大学附属第一医院采购公告"
        )
        assert result == "医院采购"


# ── _load_projects 加载逻辑测试 ───────────────────────────────────
class TestLoadProjectsIncludesFahcqmu:
    """测试 _load_projects 是否从 projects_fahcqmu 表加载 + business_type 推断"""

    def setup_method(self):
        if "app.api.routes.projects" in sys.modules:
            del sys.modules["app.api.routes.projects"]

    def test_load_projects_loads_three_tables(self):
        """_load_projects 应加载 projects_cqggzy + projects_ccgp + projects_fahcqmu"""
        fake_conn = MagicMock()
        # 完整 27 列 (与 row_to_project zip 一致)
        cols_27 = [
            ("url",), ("title",), ("category",), ("publish_date",),
            ("publish_date_raw",), ("content_preview",), ("budget",),
            ("deadline",), ("region",), ("tender_type",),
            ("keywords_matched",), ("contact_name",), ("contact_phone",),
            ("contact_email",), ("attachments_count",), ("attachments",),
            ("created_at",), ("scraped_by",), ("business_type",),
            ("info_type",), ("project_no",), ("project_overview",),
            ("bidder_requirements",), ("submission_deadline",),
            ("bid_amount",), ("full_content",), ("tender_content",),
        ]
        # 3 张表各 1 行 (所有列)
        cqggzy_row = ("url1", "t1", "工程招投标", date(2026, 6, 25), "", "", "", None, "", "工程招投标", "", "", "", "", 0, "[]", None, "", "工程招投标", "", "", "", "", "", "", "", "")
        ccgp_row = ("url2", "t2", "政府采购", date(2026, 6, 24), "", "", "", None, "", "", "", "", "", "", 0, "[]", None, "", "政府采购", "", "", "", "", "", "", "", "")
        fahcqmu_row = ("url3", "t3", None, date(2026, 6, 23), "", "", "", None, "", "", "", "", "", "", 0, "[]", datetime.now(), "", None, "", "", "", "", "", "", "", "")

        def fake_execute(sql, *args, **kwargs):
            m = MagicMock()
            m.description = cols_27
            if "LIMIT 0" in sql:
                return m
            if "FROM projects_cqggzy" in sql:
                m.fetchall.return_value = [cqggzy_row]
            elif "FROM projects_ccgp" in sql:
                m.fetchall.return_value = [ccgp_row]
            elif "FROM projects_fahcqmu" in sql:
                m.fetchall.return_value = [fahcqmu_row]
            return m

        fake_conn.execute.side_effect = fake_execute
        fake_db = MagicMock()
        fake_db._get_conn.return_value = fake_conn

        with patch("app.api.routes.projects.get_db", return_value=fake_db):
            from app.api.routes.projects import _load_projects, _clear_cache
            from app.core.harvest.data_cache import data_cache
            _clear_cache()
            data_cache.invalidate("all")  # PR feat/data-cache-v2: 新缓存层
            projects, total = _load_projects()
            assert total == 3, f"Expected 3 projects, got {total}"

            by_url = {p["url"]: p for p in projects}
            # 验证 3 张表的数据都加载了
            assert "url1" in by_url, "cqggzy row missing"
            assert "url2" in by_url, "ccgp row missing"
            assert "url3" in by_url, "fahcqmu row missing (核心修复!)"

    def test_fahcqmu_business_type_inferred_to_yiyuancaigou(self):
        """fahcqmu 行的 business_type 字段在加载后应为 '医院采购' (从 URL 推断)"""
        fake_conn = MagicMock()
        cols_27 = [
            ("url",), ("title",), ("category",), ("publish_date",),
            ("publish_date_raw",), ("content_preview",), ("budget",),
            ("deadline",), ("region",), ("tender_type",),
            ("keywords_matched",), ("contact_name",), ("contact_phone",),
            ("contact_email",), ("attachments_count",), ("attachments",),
            ("created_at",), ("scraped_by",), ("business_type",),
            ("info_type",), ("project_no",), ("project_overview",),
            ("bidder_requirements",), ("submission_deadline",),
            ("bid_amount",), ("full_content",), ("tender_content",),
        ]
        fahcqmu_row = ("https://www.fahcqmu.cn/test/1", "测试项目", None, date(2026, 6, 25), "", "摘要", "", None, "", "", "", "", "", "", 0, "[]", datetime.now(), "", None, "", "", "", "", "", "", "", "")

        def fake_execute(sql, *args, **kwargs):
            m = MagicMock()
            m.description = cols_27
            if "LIMIT 0" in sql:
                return m
            if "FROM projects_cqggzy" in sql:
                m.fetchall.return_value = []
            elif "FROM projects_ccgp" in sql:
                m.fetchall.return_value = []
            elif "FROM projects_fahcqmu" in sql:
                m.fetchall.return_value = [fahcqmu_row]
            return m

        fake_conn.execute.side_effect = fake_execute
        fake_db = MagicMock()
        fake_db._get_conn.return_value = fake_conn

        with patch("app.api.routes.projects.get_db", return_value=fake_db):
            from app.api.routes.projects import _load_projects, _clear_cache
            _clear_cache()
            projects, _ = _load_projects()
            assert len(projects) == 1
            p = projects[0]
            assert p["business_type"] == "医院采购", \
                f"Expected '医院采购', got '{p['business_type']}'"
            assert p["url"] == "https://www.fahcqmu.cn/test/1"

    def test_cqggzy_business_type_still_works(self):
        """回归测试: cqggzy URL (014001) 仍被正确识别为 '工程招投标'"""
        fake_conn = MagicMock()
        cols_27 = [
            ("url",), ("title",), ("category",), ("publish_date",),
            ("publish_date_raw",), ("content_preview",), ("budget",),
            ("deadline",), ("region",), ("tender_type",),
            ("keywords_matched",), ("contact_name",), ("contact_phone",),
            ("contact_email",), ("attachments_count",), ("attachments",),
            ("created_at",), ("scraped_by",), ("business_type",),
            ("info_type",), ("project_no",), ("project_overview",),
            ("bidder_requirements",), ("submission_deadline",),
            ("bid_amount",), ("full_content",), ("tender_content",),
        ]
        cqggzy_row = ("https://www.cqggzy.com/014001/bidding/abc", "招标项目", "工程招投标", date(2026, 6, 25), "", "", "", None, "", "", "", "", "", "", 0, "[]", datetime.now(), "", None, "", "", "", "", "", "", "", "")

        def fake_execute(sql, *args, **kwargs):
            m = MagicMock()
            m.description = cols_27
            if "LIMIT 0" in sql:
                return m
            if "FROM projects_cqggzy" in sql:
                m.fetchall.return_value = [cqggzy_row]
            elif "FROM projects_ccgp" in sql:
                m.fetchall.return_value = []
            elif "FROM projects_fahcqmu" in sql:
                m.fetchall.return_value = []
            return m

        fake_conn.execute.side_effect = fake_execute
        fake_db = MagicMock()
        fake_db._get_conn.return_value = fake_conn

        with patch("app.api.routes.projects.get_db", return_value=fake_db):
            from app.api.routes.projects import _load_projects, _clear_cache
            _clear_cache()
            projects, _ = _load_projects()
            assert len(projects) == 1
            assert projects[0]["business_type"] == "工程招投标"  # 回归


# ── /api/projects category 过滤逻辑测试 (表达式级) ───────────────
class TestProjectsCategoryFilterExpression:
    """测试 category 过滤的列表推导式 (含 business_type 匹配)"""

    def test_filter_logic_matches_business_type(self):
        """模拟 get_projects 内部 category 过滤逻辑 (3 字段 OR 匹配)"""
        projects = [
            {"url": "url1", "tender_type": "工程招投标", "type": "工程招投标", "business_type": "工程招投标"},
            {"url": "url2", "tender_type": "", "type": "", "business_type": "医院采购"},
            {"url": "url3", "tender_type": "政府采购", "type": "政府采购", "business_type": "政府采购"},
        ]
        category = "医院采购"

        # 复制 projects.py 的过滤逻辑
        filtered = [
            p for p in projects
            if p.get("tender_type") == category
            or p.get("type") == category
            or p.get("business_type") == category
        ]
        urls = [p["url"] for p in filtered]
        assert urls == ["url2"], f"Expected only fahcqmu url2, got {urls}"

    def test_filter_logic_gongcheng_regression(self):
        """回归测试: 工程招投标 过滤仍返回 cqggzy 行"""
        projects = [
            {"url": "url1", "tender_type": "工程招投标", "type": "工程招投标", "business_type": "工程招投标"},
            {"url": "url2", "tender_type": "", "type": "", "business_type": "医院采购"},
        ]
        category = "工程招投标"

        filtered = [
            p for p in projects
            if p.get("tender_type") == category
            or p.get("type") == category
            or p.get("business_type") == category
        ]
        urls = [p["url"] for p in filtered]
        assert urls == ["url1"], f"Expected only cqggzy url1, got {urls}"

    def test_filter_logic_no_category_returns_all(self):
        """无 category 过滤: 返回全部 (回归测试)"""
        projects = [
            {"url": "url1", "tender_type": "工程招投标", "type": "工程招投标", "business_type": "工程招投标"},
            {"url": "url2", "tender_type": "", "type": "", "business_type": "医院采购"},
        ]
        category = ""

        # 空 category 不进入 if 分支, 返回原列表
        filtered = projects if not category else [
            p for p in projects
            if p.get("tender_type") == category
            or p.get("type") == category
            or p.get("business_type") == category
        ]
        assert len(filtered) == 2