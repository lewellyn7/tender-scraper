"""tests/test_utils/test_clean_noise_enhance.py
2026-06-15 增强: 验证新增 3 条规则的清洗效果
- 规则 12: 【】开头占位符链
- 规则 13: 页脚备案号
- 规则 14: 信息时间变体
"""
import pytest
from app.utils.clean_noise import clean_text, make_content_preview


class TestBracketChain:
    """规则 12: 【】开头占位符链 (4126 条)"""

    def test_single_bracket(self):
        """'【】一、项目号：FLQ26B00001' → '一、项目号：FLQ26B00001'"""
        assert clean_text('【】一、项目号：FLQ26B00001 采购方式：竞争性磋商') == '一、项目号：FLQ26B00001 采购方式：竞争性磋商'

    def test_multiple_brackets(self):
        """'【】【 】【 】 一、项目号：NCQ26B00001' → '一、项目号：NCQ26B00001'"""
        assert clean_text('【】【 】【 】 一、项目号：NCQ26B00001 采购方式：竞争性磋商') == '一、项目号：NCQ26B00001 采购方式：竞争性磋商'

    def test_bracket_in_middle_kept(self):
        """中段【】保留 (e.g.【供应商必看】)"""
        s = '【供应商必看】正文内容'
        assert clean_text(s) == '【供应商必看】正文内容'

    def test_bracket_with_unicode_space(self):
        """全角空格混合"""
        assert clean_text('【】　【　】 正文') == '正文'


class TestFooter:
    """规则 13: 页脚备案号 (809 条)"""

    def test_standalone_footer(self):
        """'渝公网安备 50019002503055 号' → ''"""
        assert clean_text('渝公网安备 50019002503055 号') == ''

    def test_footer_with_id_prefix(self):
        """'1395460098222239744_2 渝公网安备 50019002503055 号' → ''"""
        assert clean_text('1395460098222239744_2 渝公网安备 50019002503055 号') == ''

    def test_footer_then_content(self):
        """'页脚\\n正文' → '正文'"""
        s = '渝公网安备 50019002503055 号\n一、项目号：ABC'
        assert clean_text(s) == '一、项目号：ABC'

    def test_content_then_footer_stripped(self):
        """'正文  渝公网安备 123 号' → '正文' (行尾也剥)"""
        s = '一、项目号：ABC\n\n渝公网安备 123 号'
        assert clean_text(s) == '一、项目号：ABC'


class TestInfoTimeVariant:
    """规则 14: 信息时间变体"""

    def test_no_colon_with_date(self):
        """'信息时间 2024-05-20 \\n正文' → '正文'"""
        assert clean_text('信息时间 2024-05-20 \n正文开始') == '正文开始'

    def test_with_colon(self):
        """'信息时间: 2024-05-20 \\n正文' → '正文'"""
        assert clean_text('信息时间: 2024-05-20 \n正文开始') == '正文开始'

    def test_chinese_colon(self):
        """'信息时间：2024-05-20 \\n正文' → '正文'"""
        assert clean_text('信息时间：2024-05-20 \n正文开始') == '正文开始'


class TestIntegrationMakePreview:
    """make_content_preview 集成测试"""

    def test_bracket_then_real_content(self):
        """【】 开头 + 真实内容 → 干净摘要"""
        fc = '【】一、项目号：FLQ26B00001 采购方式：竞争性磋商 二、项目名称：大顺镇柏坪中药材产业园灌溉项目 三、中标（成交）信息： 包号：1 供应商名称： 重庆江锦建设(集团)有限公司'
        title = '大顺镇柏坪中药材产业园灌溉项目(FLQ26B00001)中标（成交）结果公告'
        cp = make_content_preview(fc, title, max_len=300)
        assert not cp.startswith('【】')
        assert '一、项目号' in cp
        assert '包号' in cp  # 包号是真实内容, 保留

    def test_only_footer_returns_empty(self):
        """只有页脚 → cp 为空字符串"""
        fc = '渝公网安备 50019002503055 号'
        title = '某项目'
        cp = make_content_preview(fc, title, max_len=300)
        assert cp == ''

    def test_bracket_only_returns_empty(self):
        """只有【】 → cp 为空"""
        fc = '【】'
        title = '某项目'
        cp = make_content_preview(fc, title, max_len=300)
        assert cp == ''
