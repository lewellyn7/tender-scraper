"""P2 采集器性能/正确性 7 项修复 单测 (2026-06-27)

验证:
- 3.1 KeywordsService 在 cqggzy.py 循环外实例化 (count=1)
- 3.2 cqggzy_curl.py catnum 9位
- 3.3 fahcqmu.py fetch_list 有 try/except 包装 (不中断翻页)
- 3.4 ccgp.py scraped_at 用 datetime.now()
- 3.5-3.7 3 个 dict 上提到模块级
"""

import re
import ast
import sys
from pathlib import Path

import pytest

WORKTREE_ROOT = Path(__file__).resolve().parent.parent


# ============================================================================
# 3.1: KeywordsService 循环外实例化
# ============================================================================

def test_3_1_cqggzy_keywords_service_outside_loop():
    """验证 cqggzy.py 的 KeywordsService() 实例化在 for 循环外"""
    src = (WORKTREE_ROOT / "app" / "crawlers" / "cqggzy.py").read_text()

    # 找 _fetch_list_via_api 方法（KeywordsService 被调用处）
    # KeywordsService() 应在循环外实例化一次
    # 不应在 for item in items: 循环内出现 KeywordsService()
    lines = src.split('\n')
    in_loop = False
    in_method = False
    ks_in_loop = False
    ks_inst_count = 0

    for line in lines:
        if 'def _fetch_list_via_api(' in line:
            in_method = True
            continue
        if in_method and line.strip().startswith('def '):
            in_method = False
            continue
        if in_method:
            if re.match(r'\s+for item in items:', line):
                in_loop = True
                continue
            if in_loop and line.strip() and not line.startswith(' ' * 12):
                in_loop = False
            if in_loop and 'KeywordsService()' in line:
                ks_in_loop = True
            if 'KeywordsService()' in line:
                ks_inst_count += 1

    assert ks_inst_count == 1, (
        f"KeywordsService() 应只实例化 1 次 (循环外), 实际 {ks_inst_count} 次"
    )
    assert not ks_in_loop, "KeywordsService() 不应在 for item in items: 循环内"


def test_3_1_cqggzy_curl_keywords_service_outside_loop():
    """验证 cqggzy_curl.py 的 KeywordsService() 也在循环外"""
    src = (WORKTREE_ROOT / "app" / "crawlers" / "cqggzy_curl.py").read_text()

    lines = src.split('\n')
    in_loop = False
    in_method = False
    ks_in_loop = False
    ks_inst_count = 0

    for line in lines:
        if 'async def _fetch_list_via_curl(' in line:
            in_method = True
            continue
        if in_method and 'async def ' in line:
            in_method = False
            continue
        if in_method:
            if re.match(r'\s+for item in items:', line):
                in_loop = True
                continue
            if in_loop and line.strip() and not line.startswith(' ' * 12):
                in_loop = False
            if in_loop and 'KeywordsService()' in line:
                ks_in_loop = True
            if 'KeywordsService()' in line:
                ks_inst_count += 1

    assert ks_inst_count == 1, (
        f"KeywordsService() 应只实例化 1 次 (循环外), 实际 {ks_inst_count} 次"
    )
    assert not ks_in_loop, "KeywordsService() 不应在 for item in items: 循环内"


# ============================================================================
# 3.2: catnum 9位
# ============================================================================

def test_3_2_cqggzy_curl_catnum_9_digit():
    """验证 cqggzy_curl.py 传 9 位 category_num 给 _build_payload"""
    src = (WORKTREE_ROOT / "app" / "crawlers" / "cqggzy_curl.py").read_text()

    # 应有 cat9 = category_num[:9] 且 _build_payload(cat9, ...)
    assert 'cat9 = category_num[:9]' in src, "cat9 = category_num[:9] 缺失"
    assert '_build_payload(cat9,' in src, "_build_payload(cat9, ...) 缺失"
    # 不应有 cat6
    assert 'cat6' not in src or 'cat6 = category_num[:6]' not in src, (
        "不应再传 6 位 catnum"
    )


# ============================================================================
# 3.3: fahcqmu 重试
# ============================================================================

def test_3_3_fahcqmu_retry_in_get():
    """验证 fahcqmu _get 有 retries=3 参数"""
    src = (WORKTREE_ROOT / "app" / "crawlers" / "fahcqmu.py").read_text()

    assert 'retries' in src, "fahcqmu _get 缺 retries 参数"
    assert 'for attempt in range(retries)' in src, "fahcqmu _get 缺重试循环"


def test_3_3_fahcqmu_fetch_list_try_except():
    """验证 fahcqmu fetch_list_page 有 try/except 且不中断翻页"""
    src = (WORKTREE_ROOT / "app" / "crawlers" / "fahcqmu.py").read_text()

    # fetch_list_page 方法中应有 except 块 return [] 表示跳过此页
    # 定位到 def fetch_list_page 到下一个 def 之间
    in_func = False
    indent = None
    has_try = False
    has_except_return_empty = False
    for line in src.split('\n'):
        if 'def fetch_list_page(' in line:
            in_func = True
            indent = len(line) - len(line.lstrip())
            continue
        if in_func:
            if line.strip().startswith('def ') and len(line) - len(line.lstrip()) == indent:
                break
            if 'try:' in line:
                has_try = True
            if 'except' in line:
                has_try = True
            if 'return []' in line and has_try:
                has_except_return_empty = True

    assert has_try, "fetch_list_page 缺 try/except"
    assert has_except_return_empty, (
        "fetch_list_page except 后应 return [] (不中断翻页)"
    )


# ============================================================================
# 3.4: ccgp scraped_at
# ============================================================================

def test_3_4_ccgp_scraped_at_datetime_now():
    """验证 ccgp.py scraped_at 用 datetime.now() 而非 None"""
    src = (WORKTREE_ROOT / "app" / "crawlers" / "ccgp.py").read_text()

    assert '"scraped_at": None' not in src, (
        "scraped_at 不应硬编码 None"
    )
    assert "scraped_at\": datetime.now().strftime" in src, (
        "scraped_at 应用 datetime.now().strftime('%Y-%m-%d %H:%M:%S')"
    )


# ============================================================================
# 3.5-3.7: 字典上提到模块级
# ============================================================================

def test_3_5_cqggzy_category_info_type_module_level():
    """验证 cqggzy.py _CATEGORY_INFO_TYPE 在模块级 (不在函数内)"""
    src = (WORKTREE_ROOT / "app" / "crawlers" / "cqggzy.py").read_text()
    tree = ast.parse(src)

    # 检查模块级赋值
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == '_CATEGORY_INFO_TYPE':
                    return  # ✅ 在模块级

    pytest.fail("_CATEGORY_INFO_TYPE 未在 cqggzy.py 模块级定义")


def test_3_5_cqggzy_no_dict_in_loop():
    """验证 cqggzy.py _fetch_list_via_api 内不再有 _CATEGORY_INFO_TYPE dict 字面量"""
    src = (WORKTREE_ROOT / "app" / "crawlers" / "cqggzy.py").read_text()

    # 找 _fetch_list_via_api 方法内不应有 _CATEGORY_INFO_TYPE = {
    in_method = False
    for line in src.split('\n'):
        if 'def _fetch_list_via_api(' in line:
            in_method = True
            continue
        if in_method and line.strip().startswith('def '):
            break
        if in_method and '_CATEGORY_INFO_TYPE = {' in line:
            pytest.fail(f"_CATEGORY_INFO_TYPE dict 仍在 _fetch_list_via_api 内:\n{line}")


def test_3_6_cqggzy_curl_category_info_type_module_level():
    """验证 cqggzy_curl.py _CATEGORY_INFO_TYPE 在模块级"""
    src = (WORKTREE_ROOT / "app" / "crawlers" / "cqggzy_curl.py").read_text()
    tree = ast.parse(src)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == '_CATEGORY_INFO_TYPE':
                    return

    pytest.fail("_CATEGORY_INFO_TYPE 未在 cqggzy_curl.py 模块级定义")


def test_3_6_cqggzy_curl_no_dict_in_loop():
    """验证 cqggzy_curl.py _fetch_list_via_curl 内不再有 _CATEGORY_INFO_TYPE dict 字面量"""
    src = (WORKTREE_ROOT / "app" / "crawlers" / "cqggzy_curl.py").read_text()

    in_method = False
    for line in src.split('\n'):
        if 'async def _fetch_list_via_curl(' in line:
            in_method = True
            continue
        if in_method and 'async def ' in line:
            break
        if in_method and '_CATEGORY_INFO_TYPE = {' in line:
            pytest.fail(f"_CATEGORY_INFO_TYPE dict 仍在 _fetch_list_via_curl 内:\n{line}")


def test_3_7_fahcqmu_s_helper_module_level():
    """验证 fahcqmu.py _s helper 在模块级 (不在 tender_to_db_row 内)"""
    src = (WORKTREE_ROOT / "app" / "crawlers" / "fahcqmu.py").read_text()
    tree = ast.parse(src)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == '_s':
            return  # ✅ 在模块级

    pytest.fail("_s 函数未在 fahcqmu.py 模块级定义")
