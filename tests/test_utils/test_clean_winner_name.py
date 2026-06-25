"""测试 clean_winner_name 辅助函数"""
import pytest
from app.utils.bid_parser import clean_winner_name


class TestCleanWinnerName:
    """中标人名称清洗测试"""

    def test_clean_资质附注 (self):
        """去掉" 资质:..."附注"""
        raw = "重庆长寿经开区生态环境建设有限公司 资质：建筑工程施工总承包二级"
        assert clean_winner_name(raw) == "重庆长寿经开区生态环境建设有限公司"

    def test_clean_企业资质 (self):
        """去掉" 企业资质:..."附注"""
        raw = "中联宏信勘察设计有限公司 企业资质：工程勘察综合甲级"
        assert clean_winner_name(raw) == "中联宏信勘察设计有限公司"

    def test_clean_业绩附注 (self):
        """去掉" 业绩:..."附注"""
        raw = "重庆佰晟捷建筑工程有限公司 业绩：城口县 2022 年森林抚育项目"
        assert clean_winner_name(raw) == "重庆佰晟捷建筑工程有限公司"

    def test_clean_投标资格业绩 (self):
        """去掉" 投标资格业绩:..."附注"""
        raw = "广西中信恒泰工程顾问有限公司 投标资格业绩：漳州古城项目"
        assert clean_winner_name(raw) == "广西中信恒泰工程顾问有限公司"

    def test_clean_第二中标候选人 (self):
        """去掉后续中标候选人信息"""
        raw = "重庆长农建设有限公司 第二中标候选人：贵州建工集团"
        assert clean_winner_name(raw) == "重庆长农建设有限公司"

    def test_clean_第三中标候选人 (self):
        """去掉后续中标候选人信息"""
        raw = "某某公司 第三中标候选人：另一公司"
        assert clean_winner_name(raw) == "某某公司"

    def test_clean_联合体括号 (self):
        """去掉联合体成员信息"""
        raw = "信息产业电子第十一设计研究院科技工程股份有限公司（联合体成员：中贝天丰）"
        assert clean_winner_name(raw) == "信息产业电子第十一设计研究院科技工程股份有限公司"

    def test_clean_超长截断 (self):
        """超过 50 字符截断"""
        long_name = "这是一家长得不得了长得不得了长得不得了长得不得了长得不得了的公司"
        result = clean_winner_name(long_name)
        assert len(result) <= 50
        assert result.startswith("这是一家")

    def test_clean_none_input (self):
        """None 输入返回 None"""
        assert clean_winner_name(None) is None

    def test_clean_empty_input (self):
        """空字符串返回 None"""
        assert clean_winner_name("") is None
        assert clean_winner_name("   ") is None

    def test_clean_already_clean (self):
        """已经是干净名称不变"""
        clean = "重庆合一环境工程有限公司"
        assert clean_winner_name(clean) == clean

    def test_clean_单位名称后缀 (self):
        """去掉后续"单位名称:..."附注"""
        raw = "广西中信恒泰工程顾问有限公司 单位名称：工程监理综合资质"
        assert clean_winner_name(raw) == "广西中信恒泰工程顾问有限公司"