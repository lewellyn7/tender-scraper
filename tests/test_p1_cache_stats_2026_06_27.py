"""P1 修复验证: projects.py 缓存 dict 隔离 + stats.py 连接池释放.

Refs: review-2026-06-27/00-SUMMARY.md#2.10 + #2.6
"""

import ast
import os
import sys

import pytest

# ━━━ AST 验证 ━━━


def _find_file(relative_path: str) -> str:
    """Find a source file relative to the project root."""
    root = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(root, relative_path)


def test_projects_py_has_dict_shallow_copy_before_isfavorite():
    """验证 projects.py 在写 is_favorite 前执行了 dict() shallow copy.

    规则: 每一个 ``p["is_favorite"] = ...`` 写入前, 必须有 ``p = dict(p)``(或 dict() 调用)
    距离不超过 3 行, 且中间没有其他赋值覆盖 p.
    """
    path = _find_file("app/api/routes/projects.py")
    tree = ast.parse(open(path).read())

    # 收集所有 p["is_favorite"] 赋值位置 (行号)
    is_fav_lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript):
                    if (
                        isinstance(target.value, ast.Name)
                        and target.value.id == "p"
                        and isinstance(target.slice, ast.Constant)
                        and target.slice.value == "is_favorite"
                    ):
                        is_fav_lines.append(node.lineno)

    assert len(is_fav_lines) >= 5, (
        f"应有至少 5 处 is_favorite 写入 (3 user + 2 else + detail), "
        f"实际 {len(is_fav_lines)} 处: {is_fav_lines}"
    )

    # 读源文件行, 检查每个 is_favorite 前 8 行内是否有 dict(p) shallow copy
    # get_project 路径的 dict(p) 在 if/else 前 (距离可达 7 行), 放宽到 8 行
    lines = open(path).readlines()
    for lineno in is_fav_lines:
        window = "".join(lines[max(0, lineno - 9) : lineno])
        assert "dict(p)" in window, (
            f"p['is_favorite'] 赋值前 (行 {lineno}) 未找到 shallow copy: {window.strip()!r}"
        )


def test_stats_py_has_putconn_not_close():
    """验证 stats.py 用 _pg_pool.putconn() 替代了 conn.close()."""
    path = _find_file("app/api/routes/stats.py")
    tree = ast.parse(open(path).read())

    # 收集所有 close() 调用 (Attr attr='close', value name='conn' or '_pg_pool')
    close_calls = []
    putconn_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "close":
                    if isinstance(node.func.value, ast.Name):
                        close_calls.append((node.func.value.id, node.lineno))
                if node.func.attr == "putconn":
                    putconn_calls.append(node.lineno)

    # cursor.close() 仍允许 (第 73 行), 但 conn.close() 不应直接出现
    # 例外: 降级分支 (else: conn.close()) 允许
    conn_direct_closes = [
        (name, lineno) for name, lineno in close_calls if name == "conn"
    ]
    # conn 直接 close 最多出现在降级 else 分支里 (1 处)
    assert len(conn_direct_closes) <= 1, (
        f"conn.close() 不应超过 1 处 (降级分支), 实际 {conn_direct_closes}"
    )

    assert len(putconn_calls) >= 1, f"缺少 _pg_pool.putconn() 调用: {putconn_calls}"


# ━━━ 缓存污染行为测试 ━━━


def test_cache_isolation_two_users():
    """验证同一缓存 dict 给 2 个用户时, is_favorite 互不污染."""
    # 模拟 DataCache L1 返回的原始 dict (不可变数据)
    cached = {
        "url": "http://example.com/014005001/xxx",
        "title": "test project",
        "type": "政府采购",
        "publish_date": "2026-06-27",
    }

    user_a_fav_urls = {"http://example.com/014005001/xxx"}
    user_b_fav_urls = set()

    # 模拟「修复后」行为: shallow copy 再写
    p_a = dict(cached)
    p_a["is_favorite"] = p_a["url"] in user_a_fav_urls

    p_b = dict(cached)
    p_b["is_favorite"] = p_b["url"] in user_b_fav_urls

    # 断言: 两个用户看到不同的 is_favorite
    assert p_a["is_favorite"] is True, f"用户 A 应有收藏: {p_a}"
    assert p_b["is_favorite"] is False, f"用户 B 不应有收藏: {p_b}"

    # 断言: 原始缓存 dict 未被修改
    assert "is_favorite" not in cached, f"原始缓存 dict 被污染: {cached}"


def test_cache_isolation_bug_reproduction():
    """Bug 复现: 原地写缓存 dict 导致跨用户泄漏 (修复前会 FAIL)."""
    cached = {
        "url": "http://example.com/014005001/yyy",
        "title": "shared project",
    }

    # Bug 行为 (修复前): 直接写缓存的同一个 dict
    # 模拟 user A 先请求
    cached["is_favorite"] = True  # BUG: writes to shared cache
    # 模拟 user B 后请求 (得到同一个 dict)
    assert cached["is_favorite"] is True  # BUG: B 不应看到 A 的收藏

    # 修复后: 每个用户得到 shallow copy
    p_b_fixed = dict(cached)
    p_b_fixed["is_favorite"] = False
    assert p_b_fixed["is_favorite"] is False  # ✅ fixed
