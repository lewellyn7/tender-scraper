"""P1 验证: keywords.py 4 写函数有 commit() + update_keyword 占位符 PG 兼容

Fix: review-2026-06-27/00-SUMMARY.md#2.1
- Bug 1: add/update/delete/toggle 4 个写函数 execute 后缺 commit, PG 路径下静默丢数据
- Bug 2: update_keyword 用 ? 占位符, PG 路径应 %s (用 USE_PG 分支统一)
"""

import ast
import inspect
import os
import sys
from pathlib import Path

# Ensure worktree's app is importable
worktree = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(worktree))


def _extract_function_source(node) -> str:
    """Extract source text from an AST FunctionDef node if available."""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def test_all_write_functions_have_commit():
    """验证 add_keyword / update_keyword / delete_keyword / toggle_keyword 4 个写函数都有 c.commit() 调用"""

    path = worktree / "app" / "database" / "tables" / "keywords.py"
    source = path.read_text()
    tree = ast.parse(source)

    write_funcs = {"add_keyword", "update_keyword", "delete_keyword", "toggle_keyword"}
    found_funcs = set()
    missing_commit = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in write_funcs:
            found_funcs.add(node.name)
            func_source = _extract_function_source(node)
            if ".commit()" not in func_source:
                missing_commit.append(node.name)

    assert found_funcs == write_funcs, f"未找到所有写函数: missing {write_funcs - found_funcs}"
    assert len(missing_commit) == 0, f"以下函数缺 commit(): {missing_commit}"


def test_update_keyword_has_use_pg_branch():
    """验证 update_keyword 有 USE_PG 导入和 placeholder 分支"""

    path = worktree / "app" / "database" / "tables" / "keywords.py"
    source = path.read_text()
    tree = ast.parse(source)

    in_update = False
    has_use_pg_import = False
    has_placeholder_var = False
    has_commit = False

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "update_keyword":
            in_update = True
            func_source = _extract_function_source(node)
            has_use_pg_import = "USE_PG" in func_source
            has_placeholder_var = "placeholder" in func_source
            has_commit = ".commit()" in func_source

    assert in_update, "未找到 update_keyword 函数"
    assert has_use_pg_import, "update_keyword 未导入 USE_PG"
    assert has_placeholder_var, "update_keyword 未使用 placeholder 变量"
    assert has_commit, "update_keyword 缺 commit()"


def test_placeholder_switches_on_use_pg():
    """验证 placeholder 变量逻辑: USE_PG=True 则用 %s, 否则用 ?"""

    path = worktree / "app" / "database" / "tables" / "keywords.py"
    source = path.read_text()

    # 所有 4 个写函数都应该使用一致的 placeholder 模式
    for func_name in ["add_keyword", "update_keyword", "delete_keyword", "toggle_keyword"]:
        if func_name == "add_keyword":
            # add_keyword: 两个独立路径, 直接嵌入占位符
            assert "%s" in source and "?" in source, f"{func_name}: 占位符模式缺失"
        else:
            # update/delete/toggle: 使用 placeholder 变量
            assert "placeholder" in source, f"{func_name}: 未找到 placeholder 变量"
            assert '"%s" if USE_PG else "?"' in source or "'%s' if USE_PG else '?'" in source, \
                f"{func_name}: placeholder 三元表达式缺失"


def test_delete_and_toggle_have_commit():
    """验证 delete_keyword 和 toggle_keyword 都有 commit()"""

    path = worktree / "app" / "database" / "tables" / "keywords.py"
    source = path.read_text()
    tree = ast.parse(source)

    for func_name in ["delete_keyword", "toggle_keyword"]:
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                func_source = _extract_function_source(node)
                if ".commit()" in func_source:
                    found = True
        assert found, f"{func_name} 缺 commit()"


def test_no_regression_read_functions():
    """验证只读函数 (get_all/get_by_category/get_active/keywords_count) 未被意外修改"""

    path = worktree / "app" / "database" / "tables" / "keywords.py"
    source = path.read_text()
    tree = ast.parse(source)

    read_funcs = ["get_all_keywords", "get_keywords_by_category", "get_active_keywords", "keywords_count"]
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in read_funcs:
            func_source = _extract_function_source(node)
            # 只读函数不应有 commit (避免副作用)
            if ".commit()" in func_source:
                raise AssertionError(f"只读函数 {node.name} 不应有 commit()")
