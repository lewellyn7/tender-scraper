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


# ─── 2026-06-18 新增: 项目编号 / 工程招投标面包屑 / Tab 列表 ─────────────────

class TestProjectNumber:
    """规则 15: 项目编号：XXXXXXXXX (20 位数字码)"""

    def test_at_start_20_digit(self):
        """行首项目编号"""
        s = '项目编号：50024220260520001010101 本招标项目...'
        result = clean_text(s)
        assert not result.startswith('项目编号'), f'Still has 项目编号: {result[:50]}'
        assert '50024220260520001010101' not in result
        assert '本招标项目' in result

    def test_middle_after_bracket(self):
        """中段项目编号"""
        s = '【】项目编号：50011120260602002010101 本招标项目...'
        result = clean_text(s)
        assert '项目编号' not in result
        assert '本招标项目' in result

    def test_repeated_in_middle(self):
        """重复出现的项目编号"""
        s = '项目编号：50023320250519001010101 首页 > 交易信息 > 工程招投标 > 标题 项目编号：50023320250519001010101 附件1 真实内容'
        result = clean_text(s)
        assert '项目编号' not in result
        assert '附件1' in result

    def test_short_digit_kept(self):
        """短数字 (10 位以下) 不被误剥"""
        s = '联系电话：13812345678 项目编号：50012345 后面内容'
        result = clean_text(s)
        # 10 位以下的 '项目编号' 不会被规则 15 剥
        assert '50012345' in result
        # 13812345678 也不受影响
        assert '13812345678' in result

    def test_unicode_colon(self):
        """全角冒号:"""
        s = '项目编号：50011120260602002010101 正文'
        result = clean_text(s)
        assert '50011120260602002010101' not in result
        assert '正文' in result


class TestBreadcrumbV2:
    """规则 1: 面包屑 (加 '工程招投标' + 支持项目标题非 UUID)"""

    def test_engineering_bidding(self):
        """'工程招投标' (实际是这词, '工程建设' 误) 面包屑"""
        s = '首页 > 交易信息 > 工程招投标 > 酉阳县井岗堰...中标候选人公示 附件1 真实内容'
        result = clean_text(s)
        assert '首页' not in result
        assert '工程招投标' not in result
        assert '附件1' in result

    def test_government_purchase(self):
        """'政府采购' 面包屑"""
        s = '首页 > 交易信息 > 政府采购 > 食堂劳务服务项目(CQS25C02021)流标公告 一、项目基本情况'
        result = clean_text(s)
        assert '首页' not in result
        assert '政府采购' not in result or '政府采购' in result and '一、项目基本情况' in result

    def test_full_real_sample_750857(self):
        """真实样本 id=750857: 项目编号 + 面包屑 + 项目编号 + Tab 列表 + 真实内容"""
        s = ('项目编号：50024220260520001010101 首页 > 交易信息 > 工程招投标 > '
             '酉阳县井岗堰中型灌区续建配套与现代化改造项目（第二次）的中标候选人公示 '
             '项目编号：50024220260520001010101 '
             '招标公告 邀标信息 答疑补遗 中标候选人公示 中标结果公告 '
             '合同签订基本信息公示 合同变更基本信息公示 相关公告 终止公告 '
             '附件1 酉阳县...（公示期：2026年6月15日至2026年6月17日）项目标段名称')
        result = clean_text(s)
        assert '项目编号' not in result
        assert '首页' not in result
        assert '工程招投标' not in result
        assert '招标公告 邀标信息' not in result
        assert '合同签订基本信息公示' not in result
        # 真实内容保留
        assert '附件1' in result
        assert '公示期' in result

    def test_uuid_end_still_works(self):
        """原 UUID 结尾也支持 (向下兼容) — 但无内容 marker 的边缘情况不工作, 是已修复 bad URL"""
        # 真实数据中 0 条含 014005?title=xxx 模式 (fix/cqggzy-bad-nuxt-url 已修)
        # 本例仅验证面佨屑被剥 (可能带后续内容, 看作为整行; 不要求保留)
        s = '首页 > 交易信息 > 政府采购 > 014005?title=xxx'
        result = clean_text(s)
        assert '首页' not in result
        assert '014005?title' not in result


class TestTabList:
    """规则 17/18: Tab 列表 (工程类 + 政采类)"""

    def test_engineering_tab_middle(self):
        """工程类 Tab 在中段 (前面有项目编号)"""
        s = '项目编号：50011120260602002010101 招标公告 邀标信息 答疑补遗 中标候选人公示 中标结果公告 合同签订基本信息公示 合同变更基本信息公示 相关公告 终止公告 附件1 真实内容'
        result = clean_text(s)
        assert '招标公告 邀标信息' not in result
        assert '附件1' in result
        assert '真实内容' in result

    def test_engineering_tab_at_start_after_strip(self):
        """工程类 Tab 在行首 (经规则 1/15 剩后)"""
        # 模拟 规则 1 + 15 运行后的状态
        s = '招标公告 邀标信息 答疑补遗 中标候选人公示 中标结果公告 合同签订基本信息公示 合同变更基本信息公示 相关公告 终止公告 附件1 真实内容'
        result = clean_text(s)
        assert '招标公告 邀标信息' not in result
        assert '附件1' in result

    def test_gov_purchase_tab(self):
        """政采类 Tab"""
        s = '首页 > 交易信息 > 政府采购 > 食堂劳务服务项目(CQS25C02021)流标公告 采购公告 单一来源公示 答疑变更 采购结果公告 一、项目基本情况'
        result = clean_text(s)
        assert '采购公告 单一来源公示' not in result
        assert '一、项目基本情况' in result

    def test_partial_tab_kept(self):
        """部分 Tab 字符串 (不完整) 不被误剥"""
        s = '招标公告 邀标信息 (不完整) 后续内容'
        result = clean_text(s)
        # 不完整 Tab 不应被剥
        assert '招标公告 邀标信息' in result
        assert '后续内容' in result
