"""tests/test_crawlers/test_ccgp_crawler.py

CCGPCrawlerV3 单元测试
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.crawlers.ccgp import CCGPCrawlerV3
from app.models.tender import TenderInfo

# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def mock_browser():
    browser = MagicMock()
    browser.new_page = AsyncMock()
    return browser


@pytest.fixture
def crawler(mock_browser):
    return CCGPCrawlerV3(browser=mock_browser)


# ─── Mock Page ───────────────────────────────────────────────────────────────

class MockPage:
    def __init__(self, url="https://example.com", body_text="", links=None, eval_result="A"):
        self._url = url
        self._body_text = body_text
        self._links = links or []
        self._eval_result = eval_result
        self.closed = False

    @property
    def url(self):
        return self._url

    async def goto(self, url, wait_until=None, timeout=None):
        self._url = url
        return self

    async def close(self):
        self.closed = True

    async def inner_text(self, selector="body"):
        return self._body_text

    async def text_content(self):
        return self._body_text

    async def query_selector(self, selector):
        if selector == "body":
            return self
        for link in self._links:
            if link.get("_selector") == selector:
                return MockElem(link)
        # fallback - return self as a mock element
        return MockElem({"text": self._body_text, "href": "", "tag": "DIV"})

    async def query_selector_all(self, selector):
        results = []
        for link in self._links:
            if selector in str(link.get("_selector", "")):
                results.append(MockElem(link))
        return results

    async def evaluate(self, expr):
        return self._eval_result


class MockElem:
    """模拟 DOM 元素"""
    def __init__(self, data):
        self._text = data.get("text", "")
        self._href = data.get("href", "")
        self._tag = data.get("tag", "A")

    async def text_content(self):
        return self._text

    async def get_attribute(self, name):
        if name == "href":
            return self._href
        if name == "title":
            return self._text
        return None

    async def inner_text(self):
        return self._text

    async def query_selector(self, selector):
        """模拟 query_selector - 支持子选择器检查"""
        # 检查是否是元素 tag（不区分大小写）
        # e.g., selector="a" 匹配 tag="A" 或 "a"
        if selector.lower() == self._tag.lower():
            return self
        # 对于复杂选择器（类名、属性等），返回 None 表示未匹配
        # 这避免 MockElem 误导爬虫认为子元素存在
        return None

    async def query_selector_all(self, selector):
        """模拟 query_selector_all - 返回包含自身的列表"""
        return [self]


# ─── 常量测试 ────────────────────────────────────────────────────────────────

def test_ccgp_base_url(crawler):
    assert crawler.BASE_URL == "https://www.ccgp-chongqing.gov.cn"


def test_ccgp_list_urls_keys(crawler):
    assert set(crawler.LIST_URLS.keys()) == {"采购意向", "采购公告", "结果公告"}


def test_ccgp_list_urls_values(crawler):
    assert "ccgp-chongqing.gov.cn" in crawler.LIST_URLS["采购公告"]


# ─── fetch_list 测试 ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_list_invalid_type(crawler, mock_browser):
    """不支持的信息类型返回空列表"""
    results = await crawler.fetch_list(info_type="不存在的类型")
    assert results == []


@pytest.mark.asyncio
async def test_fetch_list_no_items(crawler, mock_browser):
    """列表页无数据时返回空"""
    mock_page = MockPage(body_text="暂无数据", links=[])
    mock_browser.new_page = AsyncMock(return_value=mock_page)

    results = await crawler.fetch_list(info_type="采购公告")
    assert results == []
    assert mock_page.closed is True


@pytest.mark.asyncio
async def test_fetch_list_with_items(crawler, mock_browser):
    """成功提取列表项"""
    mock_page = MockPage(
        body_text="公告内容",
        links=[
            {
                "_selector": ".notice-item",
                "text": "关于某采购项目的招标公告",
                "href": "/notice/detail/123",
                "tag": "DIV",
            },
            {
                "_selector": ".notice-item",
                "text": "另一个采购项目公告",
                "href": "/notice/detail/456",
                "tag": "DIV",
            },
        ],
    )
    mock_browser.new_page = AsyncMock(return_value=mock_page)

    results = await crawler.fetch_list(info_type="采购公告")
    assert len(results) == 2
    assert results[0].title == "关于某采购项目的招标公告"
    assert "ccgp-chongqing.gov.cn" in results[0].url
    assert results[0].info_type == "采购公告"
    assert results[0].business_type == "政府采购"
    assert mock_page.closed is True


@pytest.mark.asyncio
async def test_fetch_list_url_dedup(crawler, mock_browser):
    """相同 URL 不会重复采集"""
    mock_page = MockPage(
        body_text="公告",
        links=[
            {"_selector": ".item", "text": "项目A", "href": "/detail/1", "tag": "DIV"},
            {"_selector": ".item", "text": "项目A（重复）", "href": "/detail/1", "tag": "DIV"},
        ],
    )
    mock_browser.new_page = AsyncMock(return_value=mock_page)

    results = await crawler.fetch_list(info_type="采购意向")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_fetch_list_page_num(crawler, mock_browser):
    """分页 URL 生成"""
    captured_url = [None]  # Use list for nonlocal mutation

    async def capture_goto(url, *args, **kwargs):
        captured_url[0] = url
        return None  # goto returns None in our mock

    # Create mock page that captures the URL from goto
    mock_page = MockPage(body_text="", links=[])
    mock_page.goto = AsyncMock(side_effect=capture_goto)
    mock_browser.new_page = AsyncMock(return_value=mock_page)

    await crawler.fetch_list(info_type="采购公告", page_num=3)
    assert "page=3" in captured_url[0]


@pytest.mark.asyncio
async def test_fetch_list_skips_short_titles(crawler, mock_browser):
    """标题过短被过滤"""
    mock_page = MockPage(
        body_text="",
        links=[
            {"_selector": ".item", "text": "公告", "href": "/detail/1", "tag": "DIV"},
            {"_selector": ".item", "text": "这是一个有效标题的招标公告", "href": "/detail/2", "tag": "DIV"},
        ],
    )
    mock_browser.new_page = AsyncMock(return_value=mock_page)

    results = await crawler.fetch_list(info_type="采购公告")
    assert len(results) == 1
    assert results[0].title == "这是一个有效标题的招标公告"


# ─── fetch_detail 测试 ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_detail_skip_already_visited(crawler, mock_browser):
    """已访问的 URL 跳过采集"""
    await crawler._mark_visited("https://www.ccgp-chongqing.gov.cn/notice/detail/123")
    tender = TenderInfo(title="测试", url="https://www.ccgp-chongqing.gov.cn/notice/detail/123")

    result = await crawler.fetch_detail(tender)
    assert result.title == "测试"
    mock_browser.new_page.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_detail_success(crawler, mock_browser):
    """详情页采集成功"""
    mock_page = MockPage(
        url="https://www.ccgp-chongqing.gov.cn/notice/detail/123",
        body_text=(
            "项目概况：建设智慧城市信息系统\n"
            "预算金额：500万元\n"
            "联系人：王五\n"
            "联系电话：010-99999999\n"
            "截止时间：2024-12-31 17:00\n"
        ),
        links=[
            {"_selector": "a", "text": "采购文件.pdf", "href": "/uploads/test.pdf", "tag": "A"},
        ],
    )
    mock_browser.new_page = AsyncMock(return_value=mock_page)

    tender = TenderInfo(title="测试公告", url="https://www.ccgp-chongqing.gov.cn/notice/detail/123")
    result = await crawler.fetch_detail(tender)

    assert result.full_content is not None
    assert result.contact_info.name == "王五"
    assert result.contact_info.phone == "010-99999999"
    assert mock_page.closed is True


# ─── 信息类型专用字段提取测试 ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_intention_fields(crawler):
    """采购意向字段提取"""
    page = MockPage(body_text=(
        "采购项目名称：智慧城市一期\n"
        "预算金额：1000万元\n"
        "预计采购时间：2024年下半年\n"
        "采购需求概况：涉及大数据平台建设\n"
    ))
    tender = TenderInfo(info_type="采购意向")

    await crawler._extract_intention_fields(page, tender)

    assert tender.title == "智慧城市一期"
    assert "1000" in tender.budget
    assert "2024" in tender.bidder_requirements


@pytest.mark.asyncio
async def test_extract_notice_fields(crawler):
    """采购公告字段提取"""
    page = MockPage(body_text=(
        "项目概况：城市绿化工程\n"
        "预算金额：200万元\n"
        "供应商资格要求：具有相关资质\n"
        "投标截止时间：2024-10-15 10:00\n"
        "开标时间：2024-10-16 09:00\n"
    ))
    tender = TenderInfo(info_type="采购公告")

    await crawler._extract_notice_fields(page, tender)

    assert "绿化" in tender.project_overview
    assert "200" in tender.budget
    assert "资质" in tender.bidder_requirements
    assert tender.opening_date is not None


@pytest.mark.asyncio
async def test_extract_result_fields(crawler):
    """结果公告字段提取"""
    page = MockPage(body_text=(
        "中标供应商：北京某科技有限公司\n"
        "中标金额：150万元\n"
        "预算金额：200万元\n"
        "公告日期：2024-05-01\n"
    ))
    tender = TenderInfo(info_type="结果公告")

    await crawler._extract_result_fields(page, tender)

    assert "北京" in tender.bidder_requirements
    assert "150" in tender.bid_amount
    assert "200" in tender.budget


# ─── _summarize_content 测试 ────────────────────────────────────────────────

def test_summarize_content_purchase_intention(crawler):
    """采购意向摘要"""
    tender = TenderInfo(
        info_type="采购意向",
        title="智慧城市项目",
        budget="500万元",
        bidder_requirements="预计采购时间: 2024Q4",
    )
    summary = crawler._summarize_content(tender)
    assert "采购意向" in summary
    assert "500" in summary


def test_summarize_content_purchase_notice(crawler):
    """采购公告摘要"""
    tender = TenderInfo(
        info_type="采购公告",
        title="城区道路改造",
        project_overview="改造长度5公里",
        budget="800万元",
        submission_deadline="2024-11-30",
        bidder_requirements="具有市政资质",
    )
    summary = crawler._summarize_content(tender)
    assert "采购公告" in summary
    assert "城区道路改造" in summary
    assert "800" in summary


def test_summarize_content_result_notice(crawler):
    """结果公告摘要"""
    tender = TenderInfo(
        info_type="结果公告",
        title="中标结果公示",
        bidder_requirements="中标供应商: 甲公司",
        bid_amount="300万元",
        budget="350万元",
    )
    summary = crawler._summarize_content(tender)
    assert "结果公告" in summary
    assert "300" in summary


def test_summarize_content_with_contact(crawler):
    """带联系人的摘要"""
    from app.models.tender import ContactInfo
    tender = TenderInfo(
        info_type="采购公告",
        title="测试公告",
    )
    tender.contact_info = ContactInfo(name="张三", phone="13800000000")
    summary = crawler._summarize_content(tender)
    assert "张三" in summary


# ─── 版本信息测试 ────────────────────────────────────────────────────────────

def test_crawler_version(crawler):
    assert "tender-scraper" in crawler.version
