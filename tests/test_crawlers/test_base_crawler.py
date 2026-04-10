"""tests/test_crawlers/test_base_crawler.py

BaseCrawler 单元测试 — 测试通用工具方法
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.crawlers.base import BaseCrawler
from app.models.tender import TenderInfo

# ─── Concrete subclass for abstract testing ─────────────────────────────────

class ConcreteCrawler(BaseCrawler):
    """用于测试的具体爬虫实现"""

    BASE_URL = "https://example.com"

    async def fetch_list(self, **kwargs):
        return []

    async def fetch_detail(self, tender: TenderInfo) -> TenderInfo:
        return tender


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def mock_browser():
    browser = MagicMock()
    browser.new_page = AsyncMock()
    return browser


@pytest.fixture
def crawler(mock_browser):
    return ConcreteCrawler(browser=mock_browser)


# ─── URL 去重测试 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mark_visited_new_url(crawler):
    """新 URL 应返回 True"""
    result = await crawler._mark_visited("https://example.com/page1")
    assert result is True


@pytest.mark.asyncio
async def test_mark_visited_duplicate_url(crawler):
    """重复 URL 应返回 False"""
    await crawler._mark_visited("https://example.com/page1")
    result = await crawler._mark_visited("https://example.com/page1")
    assert result is False


@pytest.mark.asyncio
async def test_mark_visited_multiple_urls(crawler):
    """多个不同 URL 应都返回 True"""
    await crawler._mark_visited("https://example.com/page1")
    await crawler._mark_visited("https://example.com/page2")
    r1 = await crawler._mark_visited("https://example.com/page1")
    r2 = await crawler._mark_visited("https://example.com/page3")
    assert r1 is False  # page1 重复
    assert r2 is True   # page3 新增


# ─── 日期解析测试 ────────────────────────────────────────────────────────────

class TestParseDate:
    """_parse_date 各种格式测试"""

    def test_parse_date_yyyy_mm_dd(self, crawler):
        dt = crawler._parse_date("2024-01-15")
        assert dt == datetime(2024, 1, 15)

    def test_parse_date_yyyy_slash_mm_slash_dd(self, crawler):
        dt = crawler._parse_date("2024/03/22")
        assert dt == datetime(2024, 3, 22)

    def test_parse_date_chinese_format(self, crawler):
        dt = crawler._parse_date("2024年05月10日")
        assert dt == datetime(2024, 5, 10)

    def test_parse_date_dot_format(self, crawler):
        dt = crawler._parse_date("2024.07.30")
        assert dt == datetime(2024, 7, 30)

    def test_parse_date_empty(self, crawler):
        dt = crawler._parse_date("")
        assert dt is None

    def test_parse_date_with_brackets(self, crawler):
        dt = crawler._parse_date("[2024-08-01]")
        assert dt == datetime(2024, 8, 1)

    def test_parse_date_with_extra_text(self, crawler):
        dt = crawler._parse_date("发布日期：2024-09-15 10:00:00")
        assert dt == datetime(2024, 9, 15)


class TestParseDatetime:
    """_parse_datetime 各种格式测试"""

    def test_parse_datetime_standard(self, crawler):
        dt = crawler._parse_datetime("2024-01-15 14:30")
        assert dt == datetime(2024, 1, 15, 14, 30)

    def test_parse_datetime_with_seconds(self, crawler):
        dt = crawler._parse_datetime("2024-03-22 09:45:00")
        assert dt == datetime(2024, 3, 22, 9, 45)

    def test_parse_datetime_slash_format(self, crawler):
        dt = crawler._parse_datetime("2024/05/10 16:20")
        assert dt == datetime(2024, 5, 10, 16, 20)

    def test_parse_datetime_empty(self, crawler):
        dt = crawler._parse_datetime("")
        assert dt is None

    def test_parse_datetime_chinese(self, crawler):
        dt = crawler._parse_datetime("2024年05月10日 14时30分")
        assert dt == datetime(2024, 5, 10, 14, 30)


# ─── 辅助 Mock Page ──────────────────────────────────────────────────────────

class MockSelectorResult:
    """模拟 query_selector 返回结果"""
    def __init__(self, text="", href=None, tag="A"):
        self._text = text
        self._href = href
        self._tag = tag

    async def text_content(self):
        return self._text

    async def get_attribute(self, name):
        if name == "href":
            return self._href
        return None

    async def inner_text(self):
        return self._text

    async def evaluate(self, expr):
        return self._tag


class MockPage:
    """模拟 Playwright Page 对象"""
    def __init__(self, body_text="", selectors=None, links=None, url="https://example.com"):
        self._body_text = body_text
        self._selectors = selectors or {}
        self._links = links or []
        self._url = url

    @property
    def url(self):
        return self._url

    async def inner_text(self, selector):
        return self._body_text

    async def text_content(self):
        return self._body_text

    async def query_selector(self, selector):
        # 返回匹配 selector 的第一个 link
        for link in self._links:
            if link.get("_selector") == selector or selector == "body":
                return MockSelectorResult(
                    text=link.get("text", ""),
                    href=link.get("href", ""),
                    tag=link.get("tag", "A"),
                )
        if selector == "body":
            return MockSelectorResult(text=self._body_text)
        return None

    async def query_selector_all(self, selector):
        results = []
        # Handle comma-separated selectors like 'a[href$=".pdf"], a[href$=".doc"], ...'
        extensions = []
        for part in selector.split(','):
            part = part.strip()
            if '.pdf' in part:
                extensions.append('.pdf')
            elif '.doc' in part:
                extensions.append('.doc')
                extensions.append('.docx')
            elif '.xls' in part:
                extensions.append('.xls')
                extensions.append('.xlsx')
            elif '.zip' in part:
                extensions.append('.zip')
        
        for link in self._links:
            href = link.get("href", "")
            for ext in extensions:
                if href.endswith(ext):
                    results.append(MockSelectorResult(
                        text=link.get("text", ""),
                        href=href,
                        tag=link.get("tag", "A"),
                    ))
                    break
        
        return results



# ─── _extract_field 测试 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_field_match(crawler):
    """_extract_field 应返回第一个匹配的正则结果"""
    page = MockPage(body_text="预算金额：123.45万元")
    result = await crawler._extract_field(
        page,
        [r"预算金额[：:]\s*([\d,\.]+)\s*万元"]
    )
    assert result == "123.45"


@pytest.mark.asyncio
async def test_extract_field_no_match(crawler):
    """无匹配时返回默认值"""
    page = MockPage(body_text="没有金额信息")
    result = await crawler._extract_field(page, [r"预算金额[：:]\s*(\d+)"])
    assert result == ""


@pytest.mark.asyncio
async def test_extract_field_multiple_patterns(crawler):
    """尝试多个正则模式，返回第一个匹配的"""
    page = MockPage(body_text="项目预算：500万元")
    result = await crawler._extract_field(
        page,
        [
            r"预算金额[：:]\s*([\d,\.]+)\s*万元",
            r"项目预算[：:]\s*([\d,\.]+)\s*万元",
        ]
    )
    assert result == "500"


# ─── _extract_field_by_kw 测试 ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_field_by_kw_found(crawler):
    """按关键词提取字段"""
    page = MockPage(body_text="项目概况：这是一个测试项目，用于系统测试。")
    result = await crawler._extract_field_by_kw(page, ["项目概况"], max_len=200)
    assert "项目概况" in result or "测试项目" in result


@pytest.mark.asyncio
async def test_extract_field_by_kw_not_found(crawler):
    """关键词不存在时返回空"""
    page = MockPage(body_text="这是一个普通页面，没有任何关键词。")
    result = await crawler._extract_field_by_kw(page, ["项目概况", "采购需求"])
    assert result == ""


# ─── _extract_contact_info 测试 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_contact_info_basic(crawler):
    """测试联系人信息提取"""
    page = MockPage(body_text=(
        "联系人：张三\n"
        "联系电话：010-12345678\n"
        "邮箱：zhangsan@example.com\n"
        "地址：北京市朝阳区某路1号"
    ))
    contact = await crawler._extract_contact_info(page)
    assert contact.name == "张三"
    assert contact.phone == "010-12345678"
    assert contact.email == "zhangsan@example.com"
    assert "北京" in contact.address


@pytest.mark.asyncio
async def test_extract_contact_info_partial(crawler):
    """只有部分联系人信息"""
    page = MockPage(body_text="联系人：李四\n电话：13900001111")
    contact = await crawler._extract_contact_info(page)
    assert contact.name == "李四"
    assert contact.phone == "13900001111"
    assert contact.email == ""


@pytest.mark.asyncio
async def test_extract_contact_info_empty(crawler):
    """无联系人信息"""
    page = MockPage(body_text="这是一个没有联系人的页面。")
    contact = await crawler._extract_contact_info(page)
    assert contact.name == ""
    assert contact.phone == ""


@pytest.mark.asyncio
async def test_extract_contact_info_tel_keyword(crawler):
    """使用 Tel 关键词"""
    page = MockPage(body_text="Tel: 021-88888888")
    contact = await crawler._extract_contact_info(page)
    assert contact.phone == "021-88888888"


# ─── _extract_attachments 测试 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_attachments_basic(crawler):
    """测试附件提取"""
    page = MockPage(body_text="附件下载", links=[
        {"_selector": "a", "text": "采购文件.pdf", "href": "/uploads/doc.pdf", "tag": "A"},
        {"_selector": "a", "text": "清单.xlsx", "href": "/uploads/list.xlsx", "tag": "A"},
    ])
    # 需要 mock urljoin - patch BASE_URL
    crawler.BASE_URL = "https://example.com"
    attachments = await crawler._extract_attachments(page)
    assert len(attachments) == 2
    names = [a.name for a in attachments]
    assert "采购文件.pdf" in names
    assert "清单.xlsx" in names


@pytest.mark.asyncio
async def test_extract_attachments_no_links(crawler):
    """无附件链接"""
    page = MockPage(body_text="无附件", links=[])
    attachments = await crawler._extract_attachments(page)
    assert len(attachments) == 0


@pytest.mark.asyncio
async def test_extract_attachments_http_url(crawler):
    """完整 HTTP URL 附件"""
    page = MockPage(body_text="附件", links=[
        {"_selector": "a", "text": "文件.docx", "href": "https://other.com/file.docx", "tag": "A"},
    ])
    attachments = await crawler._extract_attachments(page)
    assert len(attachments) == 1
    assert attachments[0].url == "https://other.com/file.docx"
    assert attachments[0].file_type == "docx"


# ─── _extract_budget 测试 ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_budget_yuan(crawler):
    """提取预算金额（元）"""
    page = MockPage(body_text="预算金额：500000元")
    result = await crawler._extract_budget(page)
    assert "500000" in result


@pytest.mark.asyncio
async def test_extract_budget_wan(crawler):
    """提取预算金额（万元）"""
    page = MockPage(body_text="采购预算：123.45万元")
    result = await crawler._extract_budget(page)
    assert "123.45" in result


@pytest.mark.asyncio
async def test_extract_budget_no_match(crawler):
    """无预算信息"""
    page = MockPage(body_text="无预算")
    result = await crawler._extract_budget(page)
    assert result == ""


# ─── _extract_deadline 测试 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_deadline_with_datetime(crawler):
    """提取截止时间（带 datetime）"""
    page = MockPage(body_text="投标截止时间：2024-12-31 17:00")
    raw, dt = await crawler._extract_deadline(page)
    assert "2024" in raw
    assert dt is not None
    assert dt.year == 2024


@pytest.mark.asyncio
async def test_extract_deadline_date_only(crawler):
    """只有日期无时间"""
    page = MockPage(body_text="截止日期：2024-06-15")
    raw, dt = await crawler._extract_deadline(page)
    assert "2024-06-15" in raw


# ─── _extract_bid_amount 测试 ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_bid_amount(crawler):
    """提取中标金额"""
    page = MockPage(body_text="中标金额：666万元")
    result = await crawler._extract_bid_amount(page)
    assert "666" in result


@pytest.mark.asyncio
async def test_extract_bid_amount_chengjiao(crawler):
    """提取成交金额"""
    page = MockPage(body_text="成交金额：888.5万元")
    result = await crawler._extract_bid_amount(page)
    assert "888.5" in result


@pytest.mark.asyncio
async def test_extract_bid_amount_no_match(crawler):
    """无中标金额"""
    page = MockPage(body_text="暂无数据")
    result = await crawler._extract_bid_amount(page)
    assert result == ""


# ─── fetch_details_batch 测试 ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_details_batch_empty(crawler):
    """批量采集空列表"""
    results = await crawler.fetch_details_batch([])
    assert results == []


@pytest.mark.asyncio
async def test_fetch_details_batch_single(crawler, mock_browser):
    """批量采集单个 Tender"""
    mock_page = MagicMock()
    mock_page.close = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)

    tenders = [TenderInfo(title="测试", url="https://example.com/1")]
    # ConcreteCrawler.fetch_detail is not implemented (abstract),
    # so test with a crawler that has it implemented
    class RealCrawler(ConcreteCrawler):
        async def fetch_detail(self, tender):
            tender.budget = "100万元"
            return tender

    real = RealCrawler(browser=mock_browser)
    results = await real.fetch_details_batch(tenders, max_concurrent=2)
    assert len(results) == 1
    assert results[0].budget == "100万元"


# ─── _fetch_with_retry 测试 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_with_retry_success(crawler, mock_browser):
    """重试成功"""
    class GoodCrawler(ConcreteCrawler):
        call_count = 0
        async def fetch_detail(self, tender):
            GoodCrawler.call_count += 1
            tender.budget = "success"
            return tender

    real = GoodCrawler(browser=mock_browser)
    t = TenderInfo(title="test", url="https://example.com")
    result = await real._fetch_with_retry(t, max_retries=3)
    assert result.budget == "success"
    assert GoodCrawler.call_count == 1


@pytest.mark.asyncio
async def test_fetch_with_retry_failure(crawler, mock_browser):
    """重试耗尽后抛出异常"""
    class BadCrawler(ConcreteCrawler):
        async def fetch_detail(self, tender):
            raise RuntimeError("网络错误")

    real = BadCrawler(browser=mock_browser)
    t = TenderInfo(title="test", url="https://example.com")
    with pytest.raises(RuntimeError):
        await real._fetch_with_retry(t, max_retries=2)
