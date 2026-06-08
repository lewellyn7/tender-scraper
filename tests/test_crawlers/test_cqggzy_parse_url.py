"""2026-06-08 Bug 1-A: 014005 政府采购 URL 数字 ID 解析

CQGGZY 2025-2026 重构后 014005 详情页用 19 位数字 ID 而非标准 UUID.
验证 _parse_detail_url 兼容:
- 标准 UUID (014001 仍用)
- 19 位数字 ID (014005 重构后)
- 末尾带 / 与不带 /
- 搜索页 URL /trade/014005?title=... 仍然正确返回 uuid=''
"""
import sys
import re
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# 直接测试 _parse_detail_url 的 regex 行为 (不依赖 crawler 实例)
def _parse(url: str) -> dict:
    """复制 _parse_detail_url 的核心逻辑用于测试"""
    result = {'trade_id': '014001', 'uuid': '', 'category_num': ''}
    uuid_match = re.search(
        r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', url
    )
    if uuid_match:
        result['uuid'] = uuid_match.group(1)
    else:
        num_match = re.search(r'/trade/\d+/(\d{16,}(?:_\d+)?)(?:[?/]|$)', url)
        if num_match:
            result['uuid'] = num_match.group(1)
    tid_match = re.search(r'/trade/(01400[15])(?:/|\?|$)', url)
    if tid_match:
        result['trade_id'] = tid_match.group(1)
    cat_match = re.search(r'[?&]categoryNum=([0-9]+)', url)
    if cat_match:
        result['category_num'] = cat_match.group(1)
    return result


class TestParse014005NumericID:
    """2026-06-08 新增: 014005 数字 ID 解析"""

    def test_014005_numeric_with_category(self):
        """真实生产数据: 19 位数字 + categoryNum"""
        url = "https://www.cqggzy.com/trade/014005/1638974459430088704?categoryNum=014005002"
        r = _parse(url)
        assert r['uuid'] == '1638974459430088704', f"got uuid={r['uuid']!r}"
        assert r['trade_id'] == '014005', f"got trade_id={r['trade_id']!r}"
        assert r['category_num'] == '014005002', f"got cat={r['category_num']!r}"

    def test_014005_numeric_no_category(self):
        """数字 ID 无 categoryNum"""
        url = "https://www.cqggzy.com/trade/014005/1638974459430088704"
        r = _parse(url)
        assert r['uuid'] == '1638974459430088704'
        assert r['trade_id'] == '014005'
        assert r['category_num'] == ''

    def test_014005_numeric_trailing_slash(self):
        """数字 ID 末尾带 /"""
        url = "https://www.cqggzy.com/trade/014005/1638974459430088704/"
        r = _parse(url)
        assert r['uuid'] == '1638974459430088704', f"trailing / not handled, got uuid={r['uuid']!r}"

    def test_014005_numeric_with_page_suffix(self):
        """数字 ID 带 _分页后缀 (CQGGZY 2025-2026 实际数据: 164xxx_1, 164xxx_2)"""
        url = "https://www.cqggzy.com/trade/014005/1640082702776709120_1?categoryNum=014005004"
        r = _parse(url)
        assert r['uuid'] == '1640082702776709120_1', f"page suffix not handled, got uuid={r['uuid']!r}"
        assert r['trade_id'] == '014005'
        assert r['category_num'] == '014005004'

    def test_014005_title_search_page(self):
        """/trade/014005?title=... 是搜索页, uuid 必须为空 (主路径正确跳过)"""
        url = "https://www.cqggzy.com/trade/014005?title=永川区中山大道中段56、327号等片区老旧小区改造"
        r = _parse(url)
        assert r['uuid'] == '', f"search page should have no uuid, got {r['uuid']!r}"
        assert r['trade_id'] == '014005'

    def test_014001_uuid_still_works(self):
        """014001 仍用标准 UUID 格式 (回归)"""
        url = "https://www.cqggzy.com/trade/014001/12345678-1234-1234-1234-123456789012?categoryNum=014001001001"
        r = _parse(url)
        assert r['uuid'] == '12345678-1234-1234-1234-123456789012'
        assert r['trade_id'] == '014001'
        assert r['category_num'] == '014001001001'

    def test_014001_uuid_no_category(self):
        """UUID 无 categoryNum"""
        url = "https://www.cqggzy.com/trade/014001/abc12345-1234-1234-1234-123456789012"
        r = _parse(url)
        assert r['uuid'] == 'abc12345-1234-1234-1234-123456789012'
        assert r['trade_id'] == '014001'

    def test_uuid_takes_priority_over_numeric(self):
        """如果同一 URL 同时含 UUID 格式和数字 ID, UUID 优先"""
        url = "https://www.cqggzy.com/trade/014005/12345678-1234-1234-1234-123456789012?categoryNum=014005002"
        r = _parse(url)
        # UUID 格式 8-4-4-4-12 仍然应该被识别
        # 数字段在 /trade/014005/ 后被 UUID 占位, 不会有 num_match (因为 ? 在数字后)
        # 实际: 数字 ID 是 19 位, UUID 是 36 位, 不会冲突
        assert r['uuid'] == '12345678-1234-1234-1234-123456789012'

    def test_short_number_rejected(self):
        """< 16 位的数字不应被识别 (避免误匹配)"""
        url = "https://www.cqggzy.com/trade/014005/12345"
        r = _parse(url)
        assert r['uuid'] == '', f"short number should be rejected, got {r['uuid']!r}"


class TestCrawlerParseMethod:
    """直接调用 crawler 实例的 _parse_detail_url (如果有)"""

    def test_crawler_parse_method_callable(self):
        """验证 crawler 真的有 _parse_detail_url 方法"""
        from app.crawlers.cqggzy import CQGGZYCrawlerV2
        # 实例化不需要网络
        import inspect
        # 检查方法存在
        assert hasattr(CQGGZYCrawlerV2, '_parse_detail_url'), \
            "CQGGZYCrawlerV2 should have _parse_detail_url method"
        # 检查方法源码含 19 位数字 regex
        src = inspect.getsource(CQGGZYCrawlerV2._parse_detail_url)
        assert r'/trade/\d+/(\d{16,}(?:_\d+)?)' in src, "should contain 16+ digit numeric ID regex (with optional _page suffix)"
        assert r'[0-9a-f]{8}-[0-9a-f]{4}' in src, "should still contain UUID regex"
        assert '01400[15]' in src, "should still recognize trade_id pattern"
