"""7-03 单测: data.html 排序逻辑 (publish_date 优先) + filter.py category/business_type 字段.

不依赖 DB / templates, 提取排序函数 + 验证 field 映射.
"""
import os
import re
import sys
from datetime import datetime, date

import pytest


# ── 1. data.html 排序逻辑 (提取内联 sort 改为可测函数) ─────────
def sort_publish_date_desc(items):
    """从 data.html line 397 / 727 / 808 提取的逻辑.

    排序: publish_date DESC, tiebreaker id DESC
    """
    return sorted(items, key=lambda p: (
        -(datetime.fromisoformat(p['publish_date']).timestamp() if p.get('publish_date') else 0),
        -(p.get('id') or 0),
    ))


def test_sort_publish_date_desc_basic():
    items = [
        {'id': 1, 'publish_date': '2026-07-01'},
        {'id': 2, 'publish_date': '2026-07-03'},
        {'id': 3, 'publish_date': '2026-07-02'},
    ]
    sorted_items = sort_publish_date_desc(items)
    assert [i['id'] for i in sorted_items] == [2, 3, 1]


def test_sort_publish_date_desc_same_date_id_tiebreak():
    """同日按 id DESC"""
    items = [
        {'id': 10, 'publish_date': '2026-07-03'},
        {'id': 50, 'publish_date': '2026-07-03'},
        {'id': 20, 'publish_date': '2026-07-03'},
    ]
    sorted_items = sort_publish_date_desc(items)
    assert [i['id'] for i in sorted_items] == [50, 20, 10]


def test_sort_publish_date_desc_null_handling():
    """publish_date 为空/None 排到最后"""
    items = [
        {'id': 1, 'publish_date': None},
        {'id': 2, 'publish_date': '2026-07-03'},
        {'id': 3, 'publish_date': ''},
    ]
    sorted_items = sort_publish_date_desc(items)
    # id=2 在最前 (有日期), id=1 和 id=3 都是 '无日期' 平手但 id 大者前
    # 注: 我们的实现 None 和 '' 都当 0, id 大的不一定在最前, 测试关键在 id=2 第一
    assert sorted_items[0]['id'] == 2


# ── 2. data.html 文件内容验证 (避免 4 处 sort 改错) ──────────
def test_data_html_no_scraped_at_sort():
    """data.html 不应再用 scraped_at 排序 (用户拍板改 publish_date)"""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_html = os.path.join(repo_root, 'app', 'templates', 'data.html')
    if not os.path.exists(data_html):
        pytest.skip("data.html not found")
    with open(data_html) as f:
        content = f.read()
    # 找所有 .sort(function / .sort(
    sort_blocks = re.findall(r'\.sort\(function\s*\([a-z],\s*[a-z]\)\s*\{[^}]+\}', content)
    for block in sort_blocks:
        assert 'scraped_at' not in block, f"data.html 仍有 scraped_at 排序: {block}"


def test_data_html_has_publish_date_sort():
    """data.html 排序应改用 publish_date"""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_html = os.path.join(repo_root, 'app', 'templates', 'data.html')
    if not os.path.exists(data_html):
        pytest.skip("data.html not found")
    with open(data_html) as f:
        content = f.read()
    # 应有 ≥2 处 publish_date localeCompare
    assert content.count("publish_date || '').localeCompare") >= 2, \
        "data.html 应有 ≥2 处 publish_date 排序"


# ── 3. filter.py extract_project_info 字段映射 ─────────────
def test_filter_extract_returns_category_not_type_only():
    """7-03 修复: filter.py 返回 dict 应包含 'category' 字段, 不再只用 'type' 孤儿键"""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    filter_py = os.path.join(repo_root, 'app', 'utils', 'filter.py')
    if not os.path.exists(filter_py):
        pytest.skip("filter.py not found")
    with open(filter_py) as f:
        content = f.read()
    # 7-03 修复: return dict 应有 "category": category,
    assert '"category": category,' in content, \
        "filter.py 应在 return dict 中输出 'category' 字段 (DB 列名一致)"


def test_filter_extract_returns_business_type():
    """filter.py 应在 return dict 中输出 business_type"""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    filter_py = os.path.join(repo_root, 'app', 'utils', 'filter.py')
    with open(filter_py) as f:
        content = f.read()
    assert '"business_type": business_type,' in content, \
        "filter.py 应在 return dict 中输出 business_type"


# ── 4. 端到端: filter.extract_project_info 输入 TenderInfo-like 对象 ──────
def test_filter_e2e_tender_info_to_dict():
    """模拟 TenderInfo 输入, 验证返回 dict 有 category + business_type"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from app.utils.filter import TenderFilter
    except Exception as e:
        pytest.skip(f"无法 import TenderFilter: {e}")

    # 模拟 TenderInfo 对象 (SimpleNamespace)
    # filter.py 用 item.get / item[...] 双形态, dict 更稳
    item = {
        'title': '测试',
        'url': 'https://example.com/1',
        'category': '工程建设',
        'business_type': '工程招投标',
        'info_type': '招标公告',
        'publish_date': '2026-07-03',  # filter.py _fmt_date 接受 str
        'publish_date_raw': '2026-07-03',
        'source_url': 'https://example.com/list',
        'content_preview': '',
        'full_content': '',
        'budget': '',
        'deadline': None,
        'region': '',
        'tender_type': '工程建设',
        'keywords_matched': [],
        'scraped_at': '2026-07-03 16:00:00',
        'scraped_by': 'tender-scraper v3.2',
        'contact_name': '',
        'contact_phone': '',
        'contact_email': '',
        'attachments': [],
    }

    f = TenderFilter(keywords=[])
    d = f.extract_project_info(item)
    # 7-03 修复: 必须有 category 字段 (DB 列名)
    assert 'category' in d, f"dict 缺 category 字段: {d.keys()}"
    assert d['category'] == '工程建设', f"category 值错: {d.get('category')}"
    # business_type
    assert 'business_type' in d, f"dict 缺 business_type 字段: {d.keys()}"
    assert d['business_type'] == '工程招投标', f"business_type 值错: {d.get('business_type')}"
    # type alias 保留 (ReportGenerator 用)
    assert d.get('type') == '工程建设'
