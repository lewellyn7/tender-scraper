"""
test_parse_bid_results_cleaned.py — 验证 parse_bid_results 主入口输出包含 cleaned_winner_name

Bug (2026-06-27):
  parse_gov_result / parse_tender_candidate / parse_tender_result 都正确返回 cleaned_winner_name
  但 parse_bid_results 主入口 (line 608-625) 重新构造 dict 时漏掉了这个字段
  导致回填脚本写入 101 行 cleaned_winner_name 全为 NULL

修复:
  parse_bid_results 主入口包装时加 'cleaned_winner_name': r.get('cleaned_winner_name')
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.utils.bid_parser import parse_bid_results


# ─── 政府采购 (采购结果公告) ────────────────────────────────────────────────

def test_gov_result_含_cleaned_winner_name():
    """政府采购公告 → parse_bid_results 必须含 cleaned_winner_name 字段."""
    content = '''包号：1 供应商名称：西部国际传播中心有限公司 供应商地址：重庆市渝北区 中标（成交）金额：6952400.00元'''
    rows = parse_bid_results(
        content=content,
        info_type='采购结果公告',
        category='014005001',
        project_id=999990,
        url='https://test.example.com/gov.html',
        publish_date='2026-06-26',
        title='测试项目',
    )
    assert len(rows) == 1
    assert 'cleaned_winner_name' in rows[0], (
        f"parse_bid_results 输出缺 cleaned_winner_name: {list(rows[0].keys())}"
    )
    assert rows[0]['cleaned_winner_name'] == '西部国际传播中心有限公司'


def test_gov_result_cleaned_strips_appendix():
    """政府采购公告, winner_name 含资质附注 → cleaned 应去除附注."""
    content = '''包号：1 供应商名称：重庆佰晟捷建筑工程有限公司 资质：建筑工程施工总承包一级 投标资格业绩：xxx项目 中标（成交）金额：1234567.89元'''
    rows = parse_bid_results(
        content=content,
        info_type='采购结果公告',
        category='014005002',
        project_id=999991,
        url='https://test.example.com/gov2.html',
        publish_date='2026-06-26',
        title='测试',
    )
    assert len(rows) == 1
    # winner_name 应保留原文 (附注), cleaned 应去除
    assert '资质' in rows[0]['winner_name'], f"winner_name 应含原文附注: {rows[0]['winner_name']!r}"
    assert '资质' not in rows[0]['cleaned_winner_name'], (
        f"cleaned 应去除资质附注: {rows[0]['cleaned_winner_name']!r}"
    )
    assert rows[0]['cleaned_winner_name'] == '重庆佰晟捷建筑工程有限公司'


# ─── 工程招投标 (中标候选人公示) ────────────────────────────────────────────

def test_tender_candidate_含_cleaned_winner_name():
    """中标候选人公示 → parse_bid_results 必须含 cleaned_winner_name."""
    content = '''第一中标候选人：重庆建工集团股份有限公司
第二中标候选人：中铁建设集团有限公司
投标报价（元）：12345678.90'''
    rows = parse_bid_results(
        content=content,
        info_type='中标候选人公示',
        category='014001001',
        project_id=999992,
        url='https://test.example.com/tc.html',
        publish_date='2026-06-25',
        title='测试工程',
    )
    assert len(rows) >= 1
    for r in rows:
        assert 'cleaned_winner_name' in r, f"row 缺 cleaned_winner_name: {list(r.keys())}"
        assert r['cleaned_winner_name'], f"cleaned_winner_name 不能为空: {r['winner_name']!r}"


def test_tender_result_含_cleaned_winner_name():
    """中标结果公示 → parse_bid_results 必须含 cleaned_winner_name."""
    content = '''中标人名称：重庆市万州区鑫源废旧物资回收有限公司
中标金额：人民币 5,678,901.23 元'''
    rows = parse_bid_results(
        content=content,
        info_type='中标结果公示',
        category='014001004',
        project_id=999993,
        url='https://test.example.com/tr.html',
        publish_date='2026-06-26',
        title='测试中标',
    )
    assert len(rows) == 1
    assert 'cleaned_winner_name' in rows[0]
    assert rows[0]['cleaned_winner_name'] == '重庆市万州区鑫源废旧物资回收有限公司'


# ─── 废标 (返回空) ──────────────────────────────────────────────────────────

def test_aborted_returns_empty():
    """废标公告 → parse_bid_results 返回 [], 不抛错."""
    content = '本项目予以废标，现公告如下。'
    rows = parse_bid_results(
        content=content,
        info_type='中标结果公示',
        category='014001004',
        project_id=999994,
        url='https://test.example.com/aborted.html',
        publish_date='2026-06-26',
        title='废标',
    )
    assert rows == []


# ─── 回归保护 (整 dict 字段) ────────────────────────────────────────────────

def test_output_dict_has_all_required_fields():
    """回归保护: parse_bid_results 输出必须含所有 upsert_bid_results 期望的字段."""
    content = '''包号：1 供应商名称：测试公司A有限公司 中标（成交）金额：1000000.00元'''
    rows = parse_bid_results(
        content=content,
        info_type='采购结果公告',
        category='014005001',
        project_id=999995,
        url='https://test.example.com/reg.html',
        publish_date='2026-06-26',
        title='回归',
    )
    assert len(rows) == 1
    r = rows[0]
    required_fields = {
        'source', 'project_id', 'url', 'info_type', 'category',
        'package_no', 'winner_name', 'cleaned_winner_name',
        'winner_rank', 'bid_amount', 'bid_amount_num',
        'winner_score', 'publish_date', 'title', 'project_types',
    }
    missing = required_fields - set(r.keys())
    assert not missing, f"parse_bid_results 输出缺字段: {missing}\n实际 keys: {set(r.keys())}"