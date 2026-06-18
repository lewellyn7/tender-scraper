"""
test_bid_parser.py — bid_parser 单测

覆盖:
  - 废标检测
  - 金额解析 (元/万元/千分位/无效)
  - 政府采购·采购结果公告 (多包+评分表)
  - 工程招投标·中标候选人公示 (3 候选人 + 报价 + 得分)
  - 工程招投标·中标结果公示
  - 主入口包装
"""
import sys
import os
from decimal import Decimal
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.utils.bid_parser import (
    is_aborted,
    parse_amount,
    parse_gov_result,
    parse_tender_candidate,
    parse_tender_result,
    parse_bid_results,
)


# ─── 废标 ────────────────────────────────────────────────────────────────

def test_is_aborted_废标公告():
    assert is_aborted("本项目予以废标") is True
    assert is_aborted("本项目流标") is True
    assert is_aborted("决定废标，现公告如下") is True
    assert is_aborted("终止采购公告") is True
    assert is_aborted("招标失败") is True
    # 政府采购公告补充表述
    assert is_aborted("二、项目废标的原因") is True
    assert is_aborted("二、项目终止的原因") is True
    assert is_aborted("本次采购流标") is True
    assert is_aborted("合格供应商不足3家") is True
    assert is_aborted("有效投标人不足三家") is True
    assert is_aborted("废标（终止）原因：") is True


def test_is_aborted_正常公告():
    assert is_aborted("三、中标（成交）信息") is False
    assert is_aborted("") is False
    assert is_aborted(None) is False


# ─── 金额 ────────────────────────────────────────────────────────────────

def test_parse_amount_元():
    assert parse_amount("12.78元") == Decimal("12.78")
    assert parse_amount("1234.56元") == Decimal("1234.56")
    assert parse_amount("￥12.78") == Decimal("12.78")


def test_parse_amount_万元():
    assert parse_amount("1234.56万元") == Decimal("12345600.00")
    assert parse_amount("100万元") == Decimal("1000000.00")
    assert parse_amount("1234万元") == Decimal("12340000.00")


def test_parse_amount_千分位():
    assert parse_amount("1,234.56元") == Decimal("1234.56")
    assert parse_amount("1,234,567.89元") == Decimal("1234567.89")


def test_parse_amount_无效():
    assert parse_amount("--") is None
    assert parse_amount("") is None
    assert parse_amount(None) is None
    assert parse_amount("面议") is None


# ─── 政府采购 · 采购结果公告 ────────────────────────────────────────────

def test_parse_gov_result_单包():
    content = """三、中标（成交）信息：
包号：1
供应商名称：福格森（武汉）生物科技股份有限公司
供应商地址：武汉经济技术开发区枫树三路9号
中标（成交）金额：单价：12.78元"""
    rows = parse_gov_result(content)
    assert len(rows) == 1
    assert rows[0]['package_no'] == '1'
    assert rows[0]['winner_name'] == '福格森（武汉）生物科技股份有限公司'
    assert rows[0]['winner_rank'] == 1
    assert rows[0]['bid_amount_num'] == Decimal('12.78')


def test_parse_gov_result_winner_name_不跨段():
    """winner_name 必须只在“供应商地址”前, 不能贪婪跨段."""
    content = """三、中标（成交）信息：
包号：1
供应商名称：东莞市有为服饰有限公司
供应商地址：东莞市清溪镇重河村杨梅岗十巷1号201房
中标（成交）金额：586,885.50元"""
    rows = parse_gov_result(content)
    assert len(rows) == 1
    assert rows[0]['winner_name'] == '东莞市有为服饰有限公司'
    assert '供应商地址' not in rows[0]['winner_name']


def test_parse_gov_result_多包带评分表():
    content = """三、中标（成交）信息：
包号：1
供应商名称：福格森（武汉）生物科技股份有限公司
中标（成交）金额：单价：12.78元
包号：2
供应商名称：天添爱（江苏）生物科技有限公司
中标（成交）金额：单价：12.36元

七、中标（成交）候选供应商评审得分及报价表
包号：1 供应商名称 报价总得分 技术总得分 商务总得分 合计 排序
福格森（武汉）生物科技股份有限公司 28.87 51 19 98.87 1
天添爱（江苏）生物科技有限公司 30 51 17.8 98.80 2
包号：2 供应商名称 报价总得分 技术总得分 商务总得分 合计 排序
天添爱（江苏）生物科技有限公司 28.33 51 17.8 97.13 1"""
    rows = parse_gov_result(content)
    assert len(rows) == 2

    # 包 1
    assert rows[0]['package_no'] == '1'
    assert rows[0]['winner_name'] == '福格森（武汉）生物科技股份有限公司'
    assert rows[0]['bid_amount_num'] == Decimal('12.78')
    assert rows[0]['winner_score'] == Decimal('98.87')

    # 包 2
    assert rows[1]['package_no'] == '2'
    assert rows[1]['winner_name'] == '天添爱（江苏）生物科技有限公司'
    assert rows[1]['bid_amount_num'] == Decimal('12.36')
    assert rows[1]['winner_score'] == Decimal('97.13')


def test_parse_gov_result_万元金额():
    content = """三、中标（成交）信息：
包号：1
供应商名称：重庆某科技有限公司
中标（成交）金额：1234.56万元"""
    rows = parse_gov_result(content)
    assert len(rows) == 1
    assert rows[0]['bid_amount_num'] == Decimal('12345600.00')


# ─── 工程招投标 · 中标候选人公示 ────────────────────────────────────────

def test_parse_tender_candidate_3候选人():
    content = """三、中标候选人公示内容
第一中标候选人：重庆市某建设有限公司
地址：重庆市渝中区xxx
投标报价：1234.56万元
评审得分：98.87
第二中标候选人：成都市某工程公司
地址：成都市武侯区xxx
投标报价：1230.00万元
评审得分：95.20
第三中标候选人：四川某建工集团
地址：四川省xxx
投标报价：1220.00万元
评审得分：92.50"""
    rows = parse_tender_candidate(content)
    assert len(rows) == 3

    assert rows[0]['winner_rank'] == 1
    assert rows[0]['winner_name'] == '重庆市某建设有限公司'
    assert rows[0]['bid_amount_num'] == Decimal('12345600.00')
    assert rows[0]['winner_score'] == Decimal('98.87')

    assert rows[1]['winner_rank'] == 2
    assert rows[1]['winner_name'] == '成都市某工程公司'

    assert rows[2]['winner_rank'] == 3
    assert rows[2]['winner_name'] == '四川某建工集团'


def test_parse_tender_candidate_简化():
    content = """中标候选人：重庆某有限公司\n投标报价：500万元"""
    rows = parse_tender_candidate(content)
    assert len(rows) >= 1
    assert rows[0]['winner_name'] == '重庆某有限公司'


# ─── 工程招投标 · 中标结果公示 ──────────────────────────────────────────

def test_parse_tender_result_中标人():
    content = """三、中标人(单位)名称：重庆市某建设有限公司
中标金额：1234.56万元
四、其他事项..."""
    rows = parse_tender_result(content)
    assert len(rows) == 1
    assert rows[0]['winner_name'] == '重庆市某建设有限公司'
    assert rows[0]['winner_rank'] == 1
    assert rows[0]['bid_amount_num'] == Decimal('12345600.00')


def test_parse_tender_result_推荐中标():
    content = """确定中标候选人：成都某建筑集团\n中标金额：800万元"""
    rows = parse_tender_result(content)
    assert len(rows) == 1
    assert rows[0]['winner_name'] == '成都某建筑集团'


# ─── 主入口 ──────────────────────────────────────────────────────────────

def test_parse_bid_results_废标返回空():
    rows = parse_bid_results(
        content="本项目予以废标，特此公告。",
        info_type="采购结果公告",
        category="政府采购",
        project_id=123,
        url="http://example.com/abc",
        publish_date=date(2026, 6, 18),
    )
    assert rows == []


def test_parse_bid_results_政府采购():
    content = """三、中标（成交）信息：
包号：1
供应商名称：福格森公司
中标（成交）金额：12.78元"""
    rows = parse_bid_results(
        content=content,
        info_type="采购结果公告",
        category="政府采购",
        project_id=123,
        url="http://example.com/abc",
        publish_date=date(2026, 6, 18),
    )
    assert len(rows) == 1
    assert rows[0]['project_id'] == 123
    assert rows[0]['url'] == 'http://example.com/abc'
    assert rows[0]['category'] == '政府采购'
    assert rows[0]['info_type'] == '采购结果公告'
    assert rows[0]['publish_date'] == date(2026, 6, 18)


def test_parse_bid_results_工程候选():
    content = """第一中标候选人：重庆某建设有限公司\n投标报价：1234.56万元"""
    rows = parse_bid_results(
        content=content,
        info_type="中标候选人公示",
        category="工程招投标",
        project_id=456,
        url="http://example.com/def",
        publish_date=date(2026, 6, 15),
    )
    assert len(rows) == 1
    assert rows[0]['winner_rank'] == 1
    assert rows[0]['winner_name'] == '重庆某建设有限公司'


def test_parse_bid_results_工程结果():
    content = """中标人名称：成都某建筑集团\n中标金额：800万元"""
    rows = parse_bid_results(
        content=content,
        info_type="中标结果公示",
        category="工程招投标",
        project_id=789,
        url="http://example.com/ghi",
        publish_date=date(2026, 6, 10),
    )
    assert len(rows) == 1
    assert rows[0]['winner_name'] == '成都某建筑集团'
    assert rows[0]['bid_amount_num'] == Decimal('8000000.00')


def test_parse_bid_results_无关类型返回空():
    rows = parse_bid_results(
        content="招标公告：xxx",
        info_type="招标公告",
        category="工程招投标",
        project_id=1, url="x", publish_date=date(2026, 6, 1),
    )
    assert rows == []

# ============================================================
# parse_tender_result() 新格式测试 (2026-06-18)
# A 类 (老 2019-): 拟 中 标 人 + 中标金额 (万元) 3044
# B 类 (新 2024+): 中标人信息\n单位名称 + 中标金额（费率、单价等）1180000.00元
# ============================================================

def test_parse_tender_result_A类_2019老格式():
    """A 类: 拟 中 标 人 名字 (中间空格) + 中标金额 (万元) 3044"""
    content = """项目名称 潼南大佛寺旅游扶贫建设项目
拟 中 标 人 河南坤宇市政园林工程有限公司
中标金额 (万元) 3044
2019 年11月25日"""
    rows = parse_tender_result(content)
    assert len(rows) == 1
    assert rows[0]['winner_name'] == '河南坤宇市政园林工程有限公司'
    assert rows[0]['winner_rank'] == 1
    assert rows[0]['bid_amount_num'] == Decimal('30440000.00')  # 3044 万 → 30,440,000 元
    assert rows[0]['package_no'] is None


def test_parse_tender_result_B类_2024新格式_单公司():
    """B 类: 中标人信息\n单位名称 + 中标金额（费率、单价等）"""
    content = """（KJ-E09）中标结果公告
项目信息
项目名称 亚洲开发银行贷款重庆创新与人力资源能力培育系统采购
中标人信息
单位名称 江苏金智教育信息股份有限公司
中标金额（费率、单价等） 1180000.00元"""
    rows = parse_tender_result(content)
    assert len(rows) == 1
    assert rows[0]['winner_name'] == '江苏金智教育信息股份有限公司'
    assert rows[0]['winner_rank'] == 1
    assert rows[0]['bid_amount_num'] == Decimal('1180000.00')


def test_parse_tender_result_B类_联合体2公司():
    """B 类: 多公司 (联合体) 名字用顿号分开, 同一个金额"""
    content = """项目名称 本研一体智慧创新教务管理信息系统采购
中标人信息
单位名称 重庆亨飞实业集团有限公司、正方软件股份有限公司
中标金额（费率、单价等） 2880000.00元"""
    rows = parse_tender_result(content)
    assert len(rows) == 2
    assert rows[0]['winner_name'] == '重庆亨飞实业集团有限公司'
    assert rows[0]['package_no'] == '1'
    assert rows[0]['winner_rank'] == 1
    assert rows[0]['bid_amount_num'] == Decimal('2880000.00')
    assert rows[1]['winner_name'] == '正方软件股份有限公司'
    assert rows[1]['package_no'] == '2'
    assert rows[1]['winner_rank'] == 1


def test_parse_tender_result_C类_老规范():
    """C 类: 中标人：xxx + 中标金额：xxx万元"""
    content = """中标人：成都某建筑集团
中标金额：800万元"""
    rows = parse_tender_result(content)
    assert len(rows) == 1
    assert rows[0]['winner_name'] == '成都某建筑集团'
    assert rows[0]['bid_amount_num'] == Decimal('8000000.00')


def test_parse_tender_result_空内容返回空():
    """边界: 空内容"""
    assert parse_tender_result('') == []
    assert parse_tender_result(None) == []


def test_parse_tender_result_无匹配返回空():
    """边界: 内容里有"中标"字样但不是中标人"""
    content = "本项目发出中标公告，具体结果详见附件。"
    rows = parse_tender_result(content)
    assert rows == []


def test_parse_tender_result_只有名字无金额():
    """边界: 有名字但无金额 (允许 bid_amount_num=None)"""
    content = "拟 中 标 人 某科技有限公司"
    rows = parse_tender_result(content)
    assert len(rows) == 1
    assert rows[0]['winner_name'] == '某科技有限公司'
    assert rows[0]['bid_amount_num'] is None
    assert rows[0]['bid_amount'] is None


def test_parse_tender_result_过滤PDF附件噪声():
    """新格式名字字段后跟 PDF 附件名 + 履约保函, 应被过滤"""
    content = """中标人信息
单位名称 中誉设计有限公司 中标结果公示.pdf 申请履约保函/低价风险担保保函
中标金额（费率、单价等） 850000.00元"""
    rows = parse_tender_result(content)
    assert len(rows) == 1
    assert rows[0]['winner_name'] == '中誉设计有限公司'
    assert rows[0]['bid_amount_num'] == Decimal('850000.00')


def test_parse_tender_result_过滤联合体成员后缀():
    """主中标人后跟 "联合体成员" 字段, 应划断"""
    content = """中标人信息
单位名称 中机中联工程有限公司 社会信用代码：9150010720288713XA 法定代表人：赵永勃
中标金额（费率、单价等） 454239335.58元，其中：勘察费：固定综合单价投标报价"""
    rows = parse_tender_result(content)
    assert len(rows) == 1
    assert rows[0]['winner_name'] == '中机中联工程有限公司'
    assert rows[0]['bid_amount_num'] == Decimal('454239335.58')


def test_parse_tender_result_中标金额_无括号数字元():
    """边界: 中标金额 850000元 无括号无说明"""
    content = "中标人：江苏某科技公司\n中标金额 850000.00元"
    rows = parse_tender_result(content)
    assert len(rows) == 1
    assert rows[0]['winner_name'] == '江苏某科技公司'
    assert rows[0]['bid_amount_num'] == Decimal('850000.00')


def test_parse_tender_result_中标金额_有描述接续():
    """边界: 中标金额 数字 元，其中：勘察费：..."""
    content = """中标人信息
单位名称 中机中联工程有限公司
中标金额（费率、单价等） 454239335.58元，其中：勘察费：固定综合单价投标报价为109.95元/延米"""
    rows = parse_tender_result(content)
    assert len(rows) == 1
    assert rows[0]['bid_amount_num'] == Decimal('454239335.58')


def test_parse_tender_result_A类_老格式_完整字段():
    """A 类 2019 真实老格式: 名字+金额+工商注册号+组织机构+投诉受理+电话+招标人"""
    content = """项 目 名 称 潼南大佛寺-双江古镇片区旅游扶贫建设项目一期蔬菜公园入口景观工程(EPC)
拟 中 标 人 河南坤宇市政园林工程有限公司 中标金额 (万元) 3044 工商注册号 91410726MA3X69CU1F
组织机构 代码 / 投诉受理部门 重庆市潼南区发展和改革委员会 联系 电话 023-44576256
招标人：重庆市潼南区两景旅游开发有限公司 2019 年11月25日"""
    rows = parse_tender_result(content)
    assert len(rows) == 1
    assert rows[0]['winner_name'] == '河南坤宇市政园林工程有限公司'
    assert rows[0]['bid_amount_num'] == Decimal('30440000.00')  # 3044 万


def test_parse_tender_result_英文表格_咨询联系人():
    """英文+中文混合格式: 中标人名称：中电智安... 咨询受理联系人：燕先生..."""
    content = """项目名称 亚洲开发银行贷款安全类人才培养智慧教学环境升级改造设备
1 中电智安科技有限公司 19,549,995.10 ...
2 山东万博科技股份有限公司 19,907,258.06 ...
中标人名称：中电智安科技有限公司 咨询受理联系人：燕先生，鞠女士 联系电话：010-81168737"""
    rows = parse_tender_result(content)
    assert len(rows) == 1
    assert rows[0]['winner_name'] == '中电智安科技有限公司'
