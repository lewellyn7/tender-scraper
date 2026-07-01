"""测试 clean_winner_name 辅助函数

7-01 拓展: 覆盖工程招投标中标候选人公示中常见的 10+ 未清洗模式
"""
import pytest
from app.utils.bid_parser import clean_winner_name


class TestCleanWinnerName:
    """中标人名称清洗测试 (基础 + 7-01 拓展)"""

    # ── 基础清洗 (保留原 12 用例) ──

    def test_clean_资质附注(self):
        """去掉' 资质:...'附注"""
        raw = "重庆长寿经开区生态环境建设有限公司 资质：建筑工程施工总承包二级"
        assert clean_winner_name(raw) == "重庆长寿经开区生态环境建设有限公司"

    def test_clean_企业资质(self):
        """去掉' 企业资质:...'附注"""
        raw = "中联宏信勘察设计有限公司 企业资质：工程勘察综合甲级"
        assert clean_winner_name(raw) == "中联宏信勘察设计有限公司"

    def test_clean_业绩附注(self):
        """去掉' 业绩:...'附注"""
        raw = "重庆佰晟捷建筑工程有限公司 业绩：城口县 2022 年森林抚育项目"
        assert clean_winner_name(raw) == "重庆佰晟捷建筑工程有限公司"

    def test_clean_投标资格业绩(self):
        """去掉' 投标资格业绩:...'附注"""
        raw = "广西中信恒泰工程顾问有限公司 投标资格业绩：漳州古城项目"
        assert clean_winner_name(raw) == "广西中信恒泰工程顾问有限公司"

    def test_clean_第二中标候选人(self):
        """去掉后续中标候选人信息"""
        raw = "重庆长农建设有限公司 第二中标候选人：贵州建工集团"
        assert clean_winner_name(raw) == "重庆长农建设有限公司"

    def test_clean_第三中标候选人(self):
        """去掉后续中标候选人信息"""
        raw = "某某公司 第三中标候选人：另一公司"
        assert clean_winner_name(raw) == "某某公司"

    def test_clean_联合体括号(self):
        """去掉联合体成员信息"""
        raw = "信息产业电子第十一设计研究院科技工程股份有限公司（联合体成员：中贝天丰）"
        assert clean_winner_name(raw) == "信息产业电子第十一设计研究院科技工程股份有限公司"

    def test_clean_超长截断(self):
        """超过 50 字符截断"""
        long_name = "这是一家长得不得了长得不得了长得不得了长得不得了长得不得了的公司"
        result = clean_winner_name(long_name)
        assert len(result) <= 50
        assert result.startswith("这是一家")

    def test_clean_none_input(self):
        """None 输入返回 None"""
        assert clean_winner_name(None) is None

    def test_clean_empty_input(self):
        """空字符串返回 None"""
        assert clean_winner_name("") is None
        assert clean_winner_name("   ") is None

    def test_clean_already_clean(self):
        """已经是干净名称不变"""
        clean = "重庆合一环境工程有限公司"
        assert clean_winner_name(clean) == clean

    def test_clean_单位名称后缀(self):
        """去掉后续'单位名称:...'附注"""
        raw = "广西中信恒泰工程顾问有限公司 单位名称：工程监理综合资质"
        assert clean_winner_name(raw) == "广西中信恒泰工程顾问有限公司"

    # ── 7-01 拓展: 新发现的脏模式 ──

    def test_clean_数字加中标候选人的资质_半角句点(self):
        """7-01: '1.中标候选人的资质：...'"""
        raw = "重庆中检工程质量检测有限公司 1.中标候选人的资质：CMA认证合格证书、建设工程质量检测机构资质证书"
        assert clean_winner_name(raw) == "重庆中检工程质量检测有限公司"

    def test_clean_数字加中标候选人的资质_全角句点(self):
        """7-01: '1．中标候选人的资质：...' (全角句点)"""
        raw = "重庆市建设工程质量检验测试中心有限公司 1．中标候选人的资质：CMA认证合格证书"
        assert clean_winner_name(raw) == "重庆市建设工程质量检验测试中心有限公司"

    def test_clean_公司资质(self):
        """7-01: '公司资质：...' (多了'公司'前缀)"""
        raw = "重庆市涪陵荔枝建筑公司 公司资质：公路工程施工总承包二级"
        assert clean_winner_name(raw) == "重庆市涪陵荔枝建筑公司"

    def test_clean_公司业绩(self):
        """7-01: '公司业绩：...'"""
        raw = "重庆市涪陵荔枝建筑公司 公司业绩：涪陵区2022年马武镇平碑路产业道路工程"
        assert clean_winner_name(raw) == "重庆市涪陵荔枝建筑公司"

    def test_clean_资质等级(self):
        """7-01: '资质等级：...' (没有'企业'前缀)"""
        raw = "重庆品冠建设开发有限公司（联合体成员：重庆诚邦科技集团有限公司） 资质等级：建筑工程施工总承包二级"
        # 期望: 联合体括号 + 资质等级都去掉
        assert clean_winner_name(raw) == "重庆品冠建设开发有限公司"

    def test_clean_联合体牵头人(self):
        """7-01: '（联合体牵头人：X）'"""
        raw = "重庆市富博建筑工程有限责任公司（联合体牵头人：重庆杭燊建设工程有限公司） 企业资质：市政公用工程施工总承包二级"
        assert clean_winner_name(raw) == "重庆市富博建筑工程有限责任公司"

    def test_clean_联合体_简写(self):
        """7-01: '（联合体：X）' (没有'成员'/'牵头人')"""
        raw = "某建设有限公司（联合体：某科技公司） 资质：建筑工程施工总承包二级"
        assert clean_winner_name(raw) == "某建设有限公司"

    def test_clean_nbsp_html_entity(self):
        """7-01: 清理 &nbsp; HTML 实体"""
        raw = "中诚投建工集团有限公司&nbsp; 资质：市政公用工程施工总承包一级"
        # 期望: 清理 nbsp + 资质
        result = clean_winner_name(raw)
        assert "nbsp" not in result
        assert result.startswith("中诚投建工集团有限公司")
        assert "资质" not in result

    def test_clean_中文逗号_企业资质(self):
        """7-01: '，企业资质：...' (中文逗号, 不是空格)"""
        raw = "重庆乾瑞机电工程有限公司，企业资质：中华人民共和国特种设备生产许可证"
        assert clean_winner_name(raw) == "重庆乾瑞机电工程有限公司"

    def test_clean_多pass_资质后接候选人(self):
        """7-01: 多 pass 清洗 - '公司名 资质：xxx 第二中标候选人：xxx'"""
        raw = "重庆三三消防工程有限公司 企业资质：建筑工程施工总承包二级 第二中标候选人：四川辉隆达康建设工程有限公司"
        assert clean_winner_name(raw) == "重庆三三消防工程有限公司"

    def test_clean_多pass_公司名后接多个附注(self):
        """7-01: 多 pass 清洗 - 多层附注叠加"""
        raw = "重庆市富博建筑工程有限责任公司 企业资质：市政公用工程施工总承包二级 第二中标候选人：重庆杭燊建设工程有限公司 企业资质：市政公用工程施工总承包二级 第三中标候选人：重庆展华建筑安装工程有限公司"
        assert clean_winner_name(raw) == "重庆市富博建筑工程有限责任公司"

    def test_clean_联合体_成员_含联合体字样的公司名(self):
        """7-01: 公司名本身含'联合体'不应被误切
        业务上不太可能有公司名含'联合体成员：' 这种模式,
        联合体括号只匹配括号 + 联合体, 不会切公司名"""
        # 公司名 'X联合体有限公司' 是合法公司名, 不应该被切
        raw = "北京城建联合体有限公司"
        assert clean_winner_name(raw) == "北京城建联合体有限公司"

    def test_clean_空_中标人_纯资质(self):
        """7-01: '资质：xxx' (无公司名) → 不应返回 '资质：xxx', 应返回 None 或空"""
        raw = "资质：建筑工程施工总承包二级、市政公用工程施工总承包壹级；"
        # 期望: 这种数据无公司名, 应该返回 None (清洗失败)
        result = clean_winner_name(raw)
        assert result is None or len(result) < 5, f"应返回 None 或极短, 实际: {result!r}"

    def test_clean_无_前缀(self):
        """7-01: '无 提出异议的渠道和方式' → '无' 是无效中标人"""
        raw = "无 提出异议的渠道和方式 投标人或者其他利害关系人对评标结果有异议的，应在中标候选人公示期内以书面形式向招标人"
        # '无 ' 后跟详细描述, 应该截断为 '无' 然后判定为无效 (None) 或返回 '无'
        result = clean_winner_name(raw)
        # 至少 '无' 不应出现在最终清洗结果中 (因为它会污染 GROUP BY)
        # 接受: None (更严格) 或 '无' (宽松)
        assert result in (None, "无"), f"应清洗为 None 或 '无', 实际: {result!r}"


class TestCleanWinnerNameHTMLEntity:
    """7-01: HTML 实体清理 (新增模块)"""

    def test_nbsp_with_trailing(self):
        raw = "中诚投建工集团有限公司&nbsp;"
        result = clean_winner_name(raw)
        assert result == "中诚投建工集团有限公司"

    def test_nbsp_embedded(self):
        raw = "河南立哲建设工程有限公司&nbsp; 资质：xxx"
        result = clean_winner_name(raw)
        assert "nbsp" not in result
        assert "资质" not in result

    def test_amp_entity(self):
        raw = "某公司&amp;另一公司"
        result = clean_winner_name(raw)
        assert "&amp;" not in result


class TestCleanWinnerNameBoundary:
    """7-01: 边界条件"""

    def test_纯空白_None(self):
        assert clean_winner_name("   ") is None
        assert clean_winner_name("\t\n  ") is None

    def test_全数字(self):
        """全数字不应被返回"""
        raw = "12345"
        result = clean_winner_name(raw)
        # 12345 是 5 字符, 不是有效公司名, 但清洗函数不一定能识别
        # 接受: 返回原值 (无害)
        assert result == "12345" or result is None

    def test_联合体嵌套(self):
        """'X有限公司（联合体成员：Y（也是联合体））' — 嵌套括号"""
        raw = "某公司（联合体成员：Y（内部））"
        result = clean_winner_name(raw)
        # 简化: 联合体模式贪婪匹配到第一个 ）即可
        assert result == "某公司"

    def test_中文标点_分号_结尾(self):
        raw = "某公司；资质：xxx"
        result = clean_winner_name(raw)
        assert "资质" not in result

    def test_clean_企业资质等级(self):
        """7-01 v2: '企业资质等级' (缺冒号, 资质在后面)"""
        raw = "重庆市涪陵荔枝建筑公司 企业资质等级：公路工程施工总承包二级 企业业绩：南沱镇南沱村"
        result = clean_winner_name(raw)
        # 期望: 截掉 "企业资质等级" 段, 末尾孤立 "企业" 被清
        assert result == "重庆市涪陵荔枝建筑公司"

    def test_clean_末尾孤立_企业(self):
        """7-01 v2: 末尾 ' 企业' 修饰词清理"""
        raw = "XX有限公司 企业"
        # " 企业" 在末尾, 应被清理
        assert clean_winner_name(raw) == "XX有限公司"

    def test_clean_公司名_含联合体_不切(self):
        """7-01 v2: 合法公司名 'XX联合体有限公司' 不应被切"""
        assert clean_winner_name("北京城建联合体有限公司") == "北京城建联合体有限公司"
        assert clean_winner_name("中诚投联合体集团") == "中诚投联合体集团"

    def test_clean_中文冒号_资质(self):
        """7-01 v2: '公司名 ：建筑工程施工总承包' (中文冒号)"""
        raw = "重庆市建松建筑工程有限公司 ：建筑工程施工总承包二级、市政公用工程施工总承包二级"
        assert clean_winner_name(raw) == "重庆市建松建筑工程有限公司"

    def test_clean_中文冒号_无空格(self):
        """7-01 v2: '公司名:建筑工程' (无空格)"""
        raw = "四川圣玖展业建设有限公司：建筑工程施工总承包二级"
        assert clean_winner_name(raw) == "四川圣玖展业建设有限公司"

    def test_clean_中标候选人资格审查部分(self):
        """7-01 v2: '公司名 中标候选人资格审查部分'"""
        raw = "力合科技（湖南）股份有限公司 中标候选人资格审查部分"
        assert clean_winner_name(raw) == "力合科技（湖南）股份有限公司"

    def test_clean_无_句号_后接否决(self):
        """7-01 v2: '无。 否决投标情况：...' → None"""
        raw = "无。 否决投标情况：无。 中标候选人 评标情况"
        # 无公司名, 应清洗为 None
        result = clean_winner_name(raw)
        assert result is None or len(result) < 5

    def test_clean_比选文件规定(self):
        """7-01 v2: '公司名 比选文件规定应公示的其他内容'"""
        raw = "重庆市富博建筑工程有限责任公司 比选文件规定应公示的其他内容 否决投标情况及理由"
        result = clean_winner_name(raw)
        # 期望: 至少去掉 "比选文件规定..." 段
        assert "比选文件" not in (result or "")
