"""tests/test_crawlers/test_cqggzy_publish_date.py
验证 _extract_publish_date_from_content 的公告日期提取逻辑 (2026-06-15 修复)

修复点:
1. 黑名单过滤: 跳过"截止/开标/递交/截标/截稿"前后置的日期
2. 范围 Y 过滤: 跳过"X 至 Y"格式中的 Y
3. 最早优先: 公告日期通常在文件最前段
4. 标签优先: "发布日期/公告日期/公告时间"标签直接采纳, 不走黑名单

回归测试 (防止后续改动破坏):
- 014005 政府采购公告 (典型"截止日期在前"场景)
- 范围格式"X 至 Y"
- 仅截止日期 (期望 None)
"""
import pytest
from app.crawlers.cqggzy import _extract_publish_date_from_content


class TestPublishDateLabel:
    """规则 1-2: 带明确标签的日期"""

    def test_label_publish_date_cn(self):
        """'发布日期：2026-06-09' → 2026-06-09"""
        assert str(_extract_publish_date_from_content('发布日期：2026-06-09 正文...')) == '2026-06-09'

    def test_label_publish_date_iso(self):
        """'发布日期：2026-05-20' → 2026-05-20"""
        assert str(_extract_publish_date_from_content('发布日期：2026-05-20 正文...')) == '2026-05-20'

    def test_label_announce_time_cn(self):
        """'公告时间：2026年6月20日' → 2026-06-20"""
        assert str(_extract_publish_date_from_content('公告时间：2026年6月20日 ...')) == '2026-06-20'

    def test_label_announce_date(self):
        """'公告日期：2026-05-15' → 2026-05-15"""
        assert str(_extract_publish_date_from_content('公告日期：2026-05-15 ...')) == '2026-05-15'

    def test_label_after_deadline_kept(self):
        """'截止时间：2026-07-15 发布日期：2026-06-10' → 2026-06-10 (标签优先, 跳过截止)"""
        assert str(_extract_publish_date_from_content('截止时间：2026-07-15 发布日期：2026-06-10')) == '2026-06-10'

    def test_label_iso_deadline_then_publish(self):
        """'截止日期：2026-07-15 发布日期：2026-06-10' → 2026-06-10"""
        assert str(_extract_publish_date_from_content('截止日期：2026-07-15 发布日期：2026-06-10')) == '2026-06-10'


class TestPublishDateBlacklist:
    """规则 3: 黑名单过滤 (前 10 字符 + 后 20 字符)"""

    def test_gov_procurement_typical(self):
        """014005 政府采购典型: 截止日期在前段, 公告日期在中后段

        关键: '于 2026年7月1日 14:00 前递交投标文件 ... 2026年6月9日'
        → 7-1 被后置黑名单('前递交')拦截, 采纳 6-9
        """
        content = '于 2026年7月1日 14:00 前递交投标文件 ... 2026年6月9日'
        assert str(_extract_publish_date_from_content(content)) == '2026-06-09'

    def test_opening_time_then_publish(self):
        """开标时间: 7-1 + ... + 6-15 发布"""
        content = '开标时间：2026-07-01 14:00 ... 2026年6月15日'
        assert str(_extract_publish_date_from_content(content)) == '2026-06-15'

    def test_blacklist_close_then_publish(self):
        """'截止：2026-07-15 发布：2026-06-10' → 2026-06-10"""
        content = '截止：2026-07-15 发布：2026-06-10'
        assert str(_extract_publish_date_from_content(content)) == '2026-06-10'

    def test_only_deadline_returns_none(self):
        """仅截止日期 → None"""
        content = '递交截止时间：2026-07-15 14:00 ...'
        assert _extract_publish_date_from_content(content) is None


class TestPublishDateRange:
    """规则 3: 'X 至 Y' 范围格式中的 Y 应被跳过"""

    def test_612932_real_case(self):
        """真实 DB id=612932 模式: 范围 'X 至 Y' + 截止时间在末尾

        '获取文件期限：2026年6月9日 至 2026年6月16日。... 2026年7月1日 14:00 前递交'
        → 6-9 采纳 (范围 X), 6-16 跳过 (范围 Y), 7-1 跳过 (后置黑名单)
        """
        content = '获取文件期限：2026年6月9日 至 2026年6月16日。 ... 2026年7月1日 14:00 前递交'
        assert str(_extract_publish_date_from_content(content)) == '2026-06-09'


class TestPublishDateLabelAfterBlacklist:
    """边界: 标签紧跟黑名单时不应被误伤"""

    def test_label_after_deadline_full_sentence(self):
        """'于 2026年7月15日 截止。 公告日期：2026-06-10' → 2026-06-10

        关键: "公告日期"标签前 10 字符 = "7月15日 截止。 " 含"截止" → 旧版会拦截
        修复: 标签本身是明确语义, 跳过黑名单检查
        """
        content = '于 2026年7月15日 截止。 公告日期：2026-06-10'
        assert str(_extract_publish_date_from_content(content)) == '2026-06-10'

    def test_publish_date_with_extra_space(self):
        """'递交时间： 2026-07-15  正文中间间隔. 发布日期：2026-06-10' → 2026-06-10"""
        content = '递交时间： 2026-07-15  正文中间间隔. 发布日期：2026-06-10'
        assert str(_extract_publish_date_from_content(content)) == '2026-06-10'


class TestPublishDateEmpty:
    """边界: 空 / 无日期"""

    def test_empty(self):
        assert _extract_publish_date_from_content('') is None

    def test_none(self):
        assert _extract_publish_date_from_content(None) is None

    def test_no_date(self):
        assert _extract_publish_date_from_content('本项目无日期内容') is None
