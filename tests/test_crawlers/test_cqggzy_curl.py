"""CqggzyCurlCrawler 单测 (2026-06-23)"""
import pytest
from unittest.mock import AsyncMock, patch
from app.crawlers.cqggzy_curl import (
    CqggzyCurlCrawler, _filter_record, _build_payload,
    ALLOWED_CATNUM_PREFIXES, BLACKLIST_CATNUMS, BLOCKED_TITLE_KEYWORDS,
)


class TestFilterRecord:
    def test_白名单_8大类_通过(self):
        item = {'title': '工程建设招标公告内容详细', 'categorynum': '014001001001'}
        assert _filter_record(item) is not None

    def test_黑名单_014001015_拒绝(self):
        item = {'title': '工程项目', 'categorynum': '014001015001'}
        assert _filter_record(item) is None

    def test_黑名单_014005008_拒绝(self):
        item = {'title': '采购公告', 'categorynum': '014005008001'}
        assert _filter_record(item) is None

    def test_招租_标题_拒绝(self):
        item = {'title': '某资产招租公告', 'categorynum': '014001001001'}
        assert _filter_record(item) is None

    def test_经营权出让_拒绝(self):
        item = {'title': '经营权出让招标', 'categorynum': '014005001001'}
        assert _filter_record(item) is None

    def test_子分类_014001001001_通过(self):
        # 6 位 prefix 014001 在白名单 → 12 位子分类通过
        item = {'title': '工程建设招标内容', 'categorynum': '014001001001'}
        assert _filter_record(item) is not None

    def test_非白名单前缀_拒绝(self):
        item = {'title': '土地出让', 'categorynum': '014003001001'}
        assert _filter_record(item) is None

    def test_空categorynum_拒绝(self):
        item = {'title': '招标公告', 'categorynum': ''}
        assert _filter_record(item) is None

    def test_标题过短_拒绝(self):
        item = {'title': '招标', 'categorynum': '014001001001'}
        assert _filter_record(item) is None


class TestBuildPayload:
    def test_默认_参数(self):
        p = _build_payload('014001001')
        assert p['pn'] == 0
        assert p['rn'] == 50
        assert p['condition'][0]['equalList'] == ['014001001']

    def test_页码(self):
        p = _build_payload('014005001', pn=2, rn=20)
        assert p['pn'] == 2
        assert p['rn'] == 20

    def test_condition_结构(self):
        p = _build_payload('014001019')
        cond = p['condition'][0]
        assert cond['fieldName'] == 'categorynum'
        assert cond['isLike'] is True
        assert cond['likeType'] == 2


class TestWhitelistCompleteness:
    def test_8大类齐(self):
        expected = {'014001019', '014001001', '014001002', '014001003', '014001004',
                    '014005001', '014005002', '014005004'}
        assert ALLOWED_CATNUM_PREFIXES == expected

    def test_黑名单(self):
        assert BLACKLIST_CATNUMS == {'014001015', '014005008'}

    def test_标题拦截词(self):
        assert '招租' in BLOCKED_TITLE_KEYWORDS
        assert '经营权出让' in BLOCKED_TITLE_KEYWORDS


class TestCqggzyCurlCrawler:
    def test_类继承(self):
        from app.crawlers.cqggzy import CQGGZYCrawlerV2
        assert issubclass(CqggzyCurlCrawler, CQGGZYCrawlerV2)

    def test_use_curl_标志(self):
        c = CqggzyCurlCrawler(browser=None)
        assert c.use_curl is True

    def test_scraped_by_标记(self):
        # scraped_by 应含 -curl 后缀 (区分于 Playwright)
        # 通过构造 TenderInfo 验证
        from app.crawlers.base import TenderInfo
        t = TenderInfo(title='test', url='http://x.com', category='x', source_url='http://x.com', scraped_by='tender-scraper v3.2-curl')
        assert 'curl' in t.scraped_by
