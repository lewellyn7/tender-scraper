"""P1 API 一致性修复单测 (2026-06-27)

验证 4 项修复:
  1. exports.py Excel 路径不使用 favorites 表
  2. search.py 异常块不含 str(e)
  3. analytics.py health 端点有 DB 检查 + 503 路径
  4. bid_parser.py parse_tender_result 无死代码
"""

import ast
import os


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(path: str) -> str:
    p = os.path.join(REPO, path)
    with open(p) as f:
        return f.read()


# ─── 1. exports.py Excel 路径不引用 favorites 表 ───

def test_exports_excel_does_not_reference_favorites():
    """exports.py /excel 路由不应查询 favorites 表"""
    src = _read("app/api/routes/exports.py")
    tree = ast.parse(src)

    excel_func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "export_excel":
            excel_func = node
            break
    assert excel_func is not None, "export_excel 函数未找到"

    func_src = ast.get_source_segment(src, excel_func)
    assert func_src is not None

    # 不应包含 "FROM favorites"
    assert "FROM favorites" not in func_src, (
        "export_excel 仍引用 favorites 表"
    )
    assert "projects_cqggzy" in func_src, (
        "export_excel 应查询 projects_cqggzy 表"
    )


# ─── 2. search.py 异常块不含 str(e) ───

def test_search_exception_does_not_expose_str_e():
    """search.py semantic_search 异常处理不应暴露 str(e) 到响应"""
    src = _read("app/api/routes/search.py")
    tree = ast.parse(src)

    # async def → AsyncFunctionDef
    sem_func = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "semantic_search":
            sem_func = node
            break
    assert sem_func is not None, "semantic_search 函数未找到"

    func_src = ast.get_source_segment(src, sem_func)
    assert func_src is not None

    # 不应在 JSONResponse 中暴露 str(e) / f"...{e}"
    assert 'Search failed' not in func_src, (
        "semantic_search 异常块仍暴露 'Search failed: {e}'"
    )
    assert "搜索服务暂时不可用" in func_src, (
        "semantic_search 应返回泛化消息"
    )


# ─── 3. analytics.py health 端点有 DB 检查 + 503 路径 ───

def test_health_endpoint_has_db_ping_and_503():
    """analytics.py /health 端点应有 DB ping 且失败时 503"""
    src = _read("app/api/routes/analytics.py")
    tree = ast.parse(src)

    health_func = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "get_health":
            health_func = node
            break
    assert health_func is not None, "get_health 函数未找到"

    func_src = ast.get_source_segment(src, health_func)
    assert func_src is not None

    # DB ping
    assert "SELECT 1" in func_src, (
        "get_health 应包含 DB ping (SELECT 1)"
    )

    # 503
    assert "status_code=503" in func_src, (
        "get_health 应在失败时返回 503"
    )

    # unhealthy
    assert '"unhealthy"' in func_src or "'unhealthy'" in func_src, (
        "get_health 应在失败时返回 status: unhealthy"
    )

    # except 块不返回 status:"ok"
    for node in ast.walk(health_func):
        if isinstance(node, ast.ExceptHandler):
            handler_src = ast.get_source_segment(src, node)
            if handler_src and '"ok"' in handler_src:
                raise AssertionError(
                    f"get_health except 块仍返回 status:ok:\n{handler_src}"
                )


# ─── 4. bid_parser.py parse_tender_result 无死代码 ───

def test_parse_tender_result_no_dead_code_after_final_return():
    """bid_parser.py parse_tender_result 最后一个 return 后无死代码"""
    src = _read("app/utils/bid_parser.py")
    lines = src.split("\n")

    # 定位 parse_tender_result 函数范围
    func_start = None
    func_end = None
    for i, line in enumerate(lines):
        if line.strip().startswith("def parse_tender_result("):
            func_start = i  # 0-indexed
            func_indent = len(line) - len(line.lstrip())
            continue
        if func_start is not None and line.strip().startswith("def ") and i > func_start:
            cur_indent = len(line) - len(line.lstrip())
            if cur_indent <= func_indent:
                func_end = i - 1
                break

    if func_end is None:
        func_end = len(lines) - 1

    func_body = "\n".join(lines[func_start:func_end + 1])

    # 死代码特征: 旧版在 return results 后有 "模式 1: 中标人 / 中标单位" 块
    # 修复后只出现一次（在主逻辑中的注释）
    mode1_count = func_body.count("中标人 / 中标单位")
    assert mode1_count == 0, (
        f"死代码未删除: '中标人 / 中标单位' 在 func body 出现 {mode1_count} 次"
    )

    # 验证 func body 以 return results 结束 (最后一个非空非注释行)
    func_lines = func_body.split("\n")
    last_code_line = ""
    for line in reversed(func_lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            last_code_line = stripped
            break
    assert "return results" in last_code_line, (
        f"parse_tender_result 最后一行可执行代码应为 return results, 实际: {last_code_line}"
    )
