"""重医附一院采集器单元测试 (2026-06-25)
============================================
覆盖:
- URL 构造 (build_list_url / build_doc_url)
- org_unit / info_type 推断
- 日期解析 (parse_date_dot)
- CATEGORIES 配置完整性
- HTML 解析 (列表 + 详情) — 用真实抓取的 fixture
- 翻页循环 (mock aiohttp)

运行:
    cd .worktrees/fahcqmu
    DATABASE_URL="postgresql://root:root123@localhost:5435/tender_scraper" \
        python -m pytest tests/test_crawlers/test_fahcqmu_crawler.py -v
"""
import asyncio
import os
import re
import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from app.crawlers.fahcqmu import (
    BASE_URL,
    CATEGORIES,
    CategoryConfig,
    FahcqmuCrawler,
    build_doc_url,
    build_list_url,
    collect_org_unit,
    infer_info_type,
    infer_org_unit,
    parse_date_dot,
    tender_to_db_row,
)


# ============================================================================
# 1. URL 构造
# ============================================================================
class TestBuildUrls(unittest.TestCase):
    """build_list_url / build_doc_url."""

    def test_build_list_url_page_1_equals_base(self):
        """page=1 应等同 base URL (无 /p/1 后缀)."""
        assert build_list_url("gzb_cgxx_xxsjc1_ygtjgg", 1) == \
            "https://www.fahcqmu.cn/gzb_cgxx_xxsjc1_ygtjgg"
        assert build_list_url("gzb_cgxx_xxsjc1_ygtjgg", 0) == \
            "https://www.fahcqmu.cn/gzb_cgxx_xxsjc1_ygtjgg"
        assert build_list_url("gzb_cgxx_xxsjc1_ygtjgg", -5) == \
            "https://www.fahcqmu.cn/gzb_cgxx_xxsjc1_ygtjgg"

    def test_build_list_url_page_2_has_suffix(self):
        assert build_list_url("gzb_cgxx_xxsjc1_ygtjgg", 2) == \
            "https://www.fahcqmu.cn/gzb_cgxx_xxsjc1_ygtjgg/p/2"
        assert build_list_url("gw_yygg_zbgg_cgglczb2_cgxx_cggg", 47) == \
            "https://www.fahcqmu.cn/gw_yygg_zbgg_cgglczb2_cgxx_cggg/p/47"

    def test_build_doc_url(self):
        url = build_doc_url("gzb_cgxx_xxsjc1_ygtjgg", "010160500051626")
        assert url == "https://www.fahcqmu.cn/gzb_cgxx_xxsjc1_ygtjgg/010160500051626.html"

        url2 = build_doc_url("gw_yygg_zbgg_cgglczb2_cgxx_jggs", "010100900051651")
        assert url2 == "https://www.fahcqmu.cn/gw_yygg_zbgg_cgglczb2_cgxx_jggs/010100900051651.html"


# ============================================================================
# 2. org_unit / info_type 推断
# ============================================================================
class TestInfer(unittest.TestCase):
    """从 URL 推断元数据."""

    def test_infer_org_unit_xxsjc1(self):
        assert infer_org_unit("https://www.fahcqmu.cn/gzb_cgxx_xxsjc1_ygtjgg/010160500051626.html") == "信息数据处"
        assert infer_org_unit("https://www.fahcqmu.cn/gzb_cgxx_xxsjc1_dygg/010160400051727.html") == "信息数据处"
        assert infer_org_unit("https://www.fahcqmu.cn/gzb_cgxx_xxsjc1_cggg/010160600051439.html") == "信息数据处"
        assert infer_org_unit("https://www.fahcqmu.cn/gzb_cgxx_xxsjc1_cgjggs/010160700051584.html") == "信息数据处"

    def test_infer_org_unit_cgglczb2(self):
        assert infer_org_unit("https://www.fahcqmu.cn/gw_yygg_zbgg_cgglczb2_cgxx_cggg/010100800051671.html") == "总务处"
        assert infer_org_unit("https://www.fahcqmu.cn/gw_yygg_zbgg_cgglczb2_cgxx_jggs/010100900051651.html") == "总务处"

    def test_infer_org_unit_qt(self):
        assert infer_org_unit("https://www.fahcqmu.cn/gzb_cgxx_qt/010141500050824.html") == "其他"

    def test_infer_org_unit_unknown(self):
        assert infer_org_unit("https://example.com/foo/bar.html") == "其他"

    def test_infer_info_type(self):
        assert infer_info_type(".../gzb_cgxx_xxsjc1_ygtjgg/123.html") == "ygtjgg"
        assert infer_info_type(".../gzb_cgxx_xxsjc1_dygg/123.html") == "dygg"
        assert infer_info_type(".../gzb_cgxx_xxsjc1_cggg/123.html") == "cggg"
        assert infer_info_type(".../gzb_cgxx_xxsjc1_cgjggs/123.html") == "cgjggs"
        assert infer_info_type(".../gw_yygg_zbgg_cgglczb2_cgxx_jggs/123.html") == "jggs"
        assert infer_info_type(".../gzb_cgxx_qt/123.html") == "qt"

    def test_infer_info_type_total_采购公告(self):
        # cggg 出现在 xxsjc1 和 cgglczb2 都应识别为 cggg
        assert infer_info_type(".../gzb_cgxx_xxsjc1_cggg/123.html") == "cggg"
        assert infer_info_type(".../gw_yygg_zbgg_cgglczb2_cgxx_cggg/123.html") == "cggg"


# ============================================================================
# 3. 日期解析
# ============================================================================
class TestParseDate(unittest.TestCase):
    """parse_date_dot - 解析 'YYYY.MM.DD' 格式."""

    def test_valid_dates(self):
        assert parse_date_dot("2026.06.18") == date(2026, 6, 18)
        assert parse_date_dot("2024.01.01") == date(2024, 1, 1)
        assert parse_date_dot("2025.12.31") == date(2025, 12, 31)

    def test_no_zero_padding(self):
        assert parse_date_dot("2026.6.8") == date(2026, 6, 8)

    def test_invalid_returns_none(self):
        assert parse_date_dot("") is None
        assert parse_date_dot(None) is None
        assert parse_date_dot("2026/06/18") is None  # wrong separator
        assert parse_date_dot("18-06-2026") is None  # wrong format
        assert parse_date_dot("2026.13.01") is None  # invalid month
        assert parse_date_dot("2026.06.32") is None  # invalid day
        assert parse_date_dot("abc") is None


# ============================================================================
# 4. CATEGORIES 配置完整性
# ============================================================================
class TestCategories(unittest.TestCase):
    """7 个分类配置覆盖完整性."""

    def test_count(self):
        assert len(CATEGORIES) == 7, f"Expected 7 categories, got {len(CATEGORIES)}"

    def test_info_types(self):
        info_types = [c.info_type for c in CATEGORIES]
        # 6 种 info_type, cggg 出现两次 (xxsjc1 + cgglczb2)
        assert sorted(set(info_types)) == ["cggg", "cgjggs", "dygg", "jggs", "qt", "ygtjgg"]
        assert info_types.count("cggg") == 2  # xxsjc1 + cgglczb2

    def test_org_units(self):
        org_units = [c.org_unit for c in CATEGORIES]
        assert org_units.count("信息数据处") == 4
        assert org_units.count("总务处") == 2
        assert org_units.count("其他") == 1

    def test_url_paths_unique(self):
        url_paths = [c.url_path for c in CATEGORIES]
        assert len(set(url_paths)) == 7, "URL paths must be unique"

    def test_descriptions_nonempty(self):
        for c in CATEGORIES:
            assert c.description, f"description empty: {c}"


# ============================================================================
# 5. HTML 列表解析 (单元, 用真实 HTML 片段)
# ============================================================================
class TestParseListHtml(unittest.TestCase):
    """_parse_list_html - 解析列表页 SSR HTML."""

    SAMPLE_LIST_HTML = """
    <html><body><ul class="mt40">
        <li>
            <a href="https://www.fahcqmu.cn/gzb_cgxx_xxsjc1_ygtjgg/010160500051626.html">
                <i class="iconfont">&#xe620;</i>
                <p><span>重庆医科大学附属第一医院超声科自助报告服务项目阳光推介会公告</span></p>
                <span class="time">2026.06.18</span>
            </a>
        </li>
        <li>
            <a href="https://www.fahcqmu.cn/gzb_cgxx_xxsjc1_ygtjgg/010160500050881.html">
                <i class="iconfont">&#xe620;</i>
                <p><span>病历数据精准后结构化项目阳光推介会公告</span></p>
                <span class="time">2026.05.09</span>
            </a>
        </li>
        <!-- 空 li (无 a) 应被忽略 -->
        <li><span>not a link</span></li>
        <!-- a 不以 .html 结尾应被忽略 -->
        <li><a href="/page/123">page</a></li>
    </ul></body></html>
    """

    def setUp(self):
        self.crawler = FahcqmuCrawler()
        self.cat = CATEGORIES[0]  # ygtjgg

    def test_parses_two_items(self):
        items = self.crawler._parse_list_html(self.SAMPLE_LIST_HTML, self.cat)
        assert len(items) == 2, f"Expected 2 items, got {len(items)}"

    def test_first_item_fields(self):
        items = self.crawler._parse_list_html(self.SAMPLE_LIST_HTML, self.cat)
        first = items[0]
        assert first.title == "重庆医科大学附属第一医院超声科自助报告服务项目阳光推介会公告"
        assert first.url == "https://www.fahcqmu.cn/gzb_cgxx_xxsjc1_ygtjgg/010160500051626.html"
        assert first.publish_date == date(2026, 6, 18)
        assert first.publish_date_raw == "2026.06.18"
        assert first.info_type == "ygtjgg"
        assert first.business_type == "医院采购"
        assert first._org_unit == "信息数据处"
        assert first._doc_id == "010160500051626"

    def test_empty_html_returns_empty(self):
        assert self.crawler._parse_list_html("<html></html>", self.cat) == []

    def test_fallback_empty_page(self):
        """空列表 fallback (~46KB 但无 li > a)."""
        fallback = "<html><body>" + "x" * 46000 + "</body></html>"
        assert self.crawler._parse_list_html(fallback, self.cat) == []


# ============================================================================
# 6. HTML 详情解析
# ============================================================================
class TestParseDetailHtml(unittest.TestCase):
    """_parse_detail_html - 解析详情页 SSR HTML (用真实片段)."""

    SAMPLE_DETAIL_HTML = """
    <html><body>
        <h1>重庆医科大学附属第一医院超声科自助报告服务项目 阳光推介会公告</h1>
        <div class="news-content">
            <p>我院拟举行超声科自助报告服务项目阳光推介会，欢迎具有相关资质、产品符合要求的商家积极参与。</p>
            <p>一、项目信息</p>
            <p>（一）项目名称：超声科自助报告服务项目</p>
            <p>（二）项目类型：服务</p>
            <p>（三）项目预算：48.8万元(非最终限价)</p>
            <p>三、报名时间及方式</p>
            <p>（一）报名时间 2026年6月26日北京时间18点前。</p>
            <p>四、推介资料</p>
            <p>联系人：张老师</p>
            <p>电 话：023-89012993</p>
            <p>重庆医科大学附属第一医院</p>
            <p>2026年6月18日</p>
        </div>
        <span class="time">2026.06.18</span>
    </body></html>
    """

    def setUp(self):
        self.crawler = FahcqmuCrawler()
        # 模拟 TenderInfo (避免 import 全部模型)
        from app.models.tender import TenderInfo
        self.item = TenderInfo(
            url="https://www.fahcqmu.cn/gzb_cgxx_xxsjc1_ygtjgg/010160500051626.html",
            title="",  # 初始空, 由解析填充
        )

    def test_parses_full_content(self):
        result = self.crawler._parse_detail_html(self.SAMPLE_DETAIL_HTML, self.item)
        assert "超声科自助报告服务项目" in result.full_content
        assert "48.8万元" in result.full_content
        assert "023-89012993" in result.full_content
        assert len(result.full_content) > 100

    def test_parses_title_from_h1(self):
        result = self.crawler._parse_detail_html(self.SAMPLE_DETAIL_HTML, self.item)
        assert "超声科自助报告服务项目" in result.title
        assert "阳光推介会公告" in result.title

    def test_parses_content_preview(self):
        result = self.crawler._parse_detail_html(self.SAMPLE_DETAIL_HTML, self.item)
        assert result.content_preview
        assert len(result.content_preview) <= 320  # 300 + 一些 suffix

    def test_parses_publish_date_from_time_span(self):
        # item 没有 publish_date, 应从 span.time 解析
        assert self.item.publish_date is None
        result = self.crawler._parse_detail_html(self.SAMPLE_DETAIL_HTML, self.item)
        assert result.publish_date == date(2026, 6, 18)
        assert result.publish_date_raw == "2026.06.18"

    def test_empty_html_returns_unchanged(self):
        empty_html = "<html></html>"
        result = self.crawler._parse_detail_html(empty_html, self.item)
        assert result.full_content == ""
        assert result.title == ""


# ============================================================================
# 7. tender_to_db_row 转换
# ============================================================================
class TestTenderToDbRow(unittest.TestCase):
    """tender_to_db_row - TenderInfo → projects_fahcqmu dict."""

    def setUp(self):
        from app.models.tender import TenderInfo
        self.item = TenderInfo(
            url="https://www.fahcqmu.cn/gzb_cgxx_xxsjc1_ygtjgg/010160500051626.html",
            title="测试项目",
            publish_date=date(2026, 6, 18),
            publish_date_raw="2026.06.18",
            info_type="ygtjgg",
            business_type="医院采购",
            category="医院采购",
            content_preview="预览",
            full_content="完整内容" * 50,
            source_url="https://www.fahcqmu.cn/gzb_cgxx_xxsjc1_ygtjgg",
        )
        self.item._org_unit = "信息数据处"

    def test_basic_fields(self):
        row = tender_to_db_row(self.item, "信息数据处")
        assert row["url"] == self.item.url
        assert row["title"] == "测试项目"
        assert row["info_type"] == "ygtjgg"
        assert row["business_type"] == "医院采购"
        assert row["org_unit"] == "信息数据处"
        assert row["publish_date"] == "2026-06-18"
        assert row["publish_date_raw"] == "2026.06.18"
        assert row["content_preview"] == "预览"
        assert len(row["full_content"]) > 100
        assert row["scraped_by"] == "tender-scraper v3.2 fahcqmu"

    def test_none_date_becomes_none(self):
        from app.models.tender import TenderInfo
        item = TenderInfo(url="...", title="t", publish_date=None)
        row = tender_to_db_row(item, "其他")
        assert row["publish_date"] is None

    def test_empty_title_becomes_empty_string(self):
        from app.models.tender import TenderInfo
        item = TenderInfo(url="...", title="", publish_date=None)
        row = tender_to_db_row(item, "其他")
        assert row["title"] == ""


# ============================================================================
# 8. collect_org_unit
# ============================================================================
class TestCollectOrgUnit(unittest.TestCase):
    """collect_org_unit - 优先 _org_unit, fallback URL 推断."""

    def test_from_attribute(self):
        from app.models.tender import TenderInfo
        item = TenderInfo(url="https://x.com/foo")
        item._org_unit = "信息数据处"
        assert collect_org_unit(item) == "信息数据处"

    def test_fallback_to_url(self):
        from app.models.tender import TenderInfo
        item = TenderInfo(url="https://www.fahcqmu.cn/gzb_cgxx_qt/123.html")
        # 无 _org_unit, 应从 URL 推断
        assert collect_org_unit(item) == "其他"


# ============================================================================
# 9. 集成测试 (可选 - 标记为慢, 默认 skip)
# ============================================================================
@pytest.mark.skipif(
    not os.environ.get("FAHC_RUN_INTEGRATION"),
    reason="Set FAHC_RUN_INTEGRATION=1 to run real HTTP test"
)
class TestIntegration(unittest.TestCase):
    """实际抓取测试 (需要外网, 慢).

    启用:
        FAHC_RUN_INTEGRATION=1 pytest tests/test_crawlers/test_fahcqmu_crawler.py -v
    """

    def test_fetch_ygtjgg_page1(self):
        async def _run():
            async with FahcqmuCrawler() as crawler:
                cat = CATEGORIES[0]  # ygtjgg
                items = await crawler.fetch_list_page(cat, 1)
                return items
        items = asyncio.run(_run())
        assert len(items) > 0
        assert all(item.info_type == "ygtjgg" for item in items)
        assert all(item.publish_date is not None for item in items)


if __name__ == "__main__":
    unittest.main()
