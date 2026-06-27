"""P2 API 三项修复验证: SQL 参数化 / 旧 cache 删除 / page_size 上限降
   3.8  analytics.py:507 INTERVAL 字符串拼 → 参数化
   3.9  projects.py:700-708 旧 _cache 端点删除
   3.10 projects.py:280  page_size 20000→5000
"""
import ast


def _parse(path: str) -> ast.Module:
    with open(path) as f:
        return ast.parse(f.read())


# ━━━ 3.8: analytics.py SQL 参数化 ━━━

def test_3_8_analytics_no_fstring_sql_days():
    """analytics.py:507 不再用 f-string 把 days 拼进 SQL 字符串"""
    import re

    with open("app/api/routes/analytics.py") as f:
        lines = f.readlines()

    # 在 _compute_daily_health_trends 函数内 (行 470+),
    # 不应出现 f""" 或 f''' 开头的 execute 调用
    in_trends = False
    for i, line in enumerate(lines, start=1):
        if "def _compute_daily_health_trends" in line:
            in_trends = True
            continue
        if in_trends:
            if line.strip().startswith("def ") and "_compute_daily_health_trends" not in line:
                break  # 下一个函数开始，退出
            # 不应该有 f""" ... INTERVAL ... f-string 拼接
            if "cur.execute(f" in line or "cur.execute(f" in line:
                raise AssertionError(
                    f"_compute_daily_health_trends 内不应有 f-string execute, 行 {i}: {line.strip()}"
                )

    # 确认使用了参数化: INTERVAL %s days (非 f-string)
    src = "".join(lines)
    assert "INTERVAL %s days" in src, (
        "analytics.py 应使用参数化 INTERVAL %s days"
    )
    assert "' -' || %s || ' days'" in src or "'-' || %s || ' days'" in src, (
        "analytics.py SQLite fallback 应使用参数化 datetime('now', '-' || %s || ' days')"
    )


# ━━━ 3.9: projects.py 旧 _cache 端点删除 ━━━

def test_3_9_projects_no_old_cache_endpoint():
    """projects.py 不再有引用未定义 _cache 旧端点"""
    with open("app/api/routes/projects.py") as f:
        src = f.read()

    # _cache["projects"] 和 _cache["last_load"] 应该不存在（旧端点已删除）
    assert '_cache["projects"]' not in src, (
        "projects.py 不应有旧 _cache 引用（端点已删）"
    )
    assert '_cache["last_load"]' not in src, (
        "projects.py 不应有旧 _cache 引用（端点已删）"
    )

    # 确认 DataCache v2 端点仍存在
    assert "/internal/cache/clear" in src, "DataCache v2 clear 端点应保留"
    assert "/internal/cache/stats" in src, "DataCache v2 stats 端点应保留"
    assert "data_cache.invalidate" in src, "DataCache v2 invalidate 调用应保留"


# ━━━ 3.10: projects.py page_size 上限 5000 ━━━

def test_3_10_projects_page_size_max():
    """projects.py page_size 上限应为 5000，不是 20000"""
    with open("app/api/routes/projects.py") as f:
        src = f.read()

    # page_size le 应该是 5000
    import re
    m = re.search(r'page_size.*Query\(.*\ble=(\d+)\)', src)
    assert m, "找不到 page_size Query 定义"
    le_val = int(m.group(1))
    assert le_val == 5000, f"page_size le 应为 5000，实际 {le_val}"
    assert le_val <= 5000, f"page_size le={le_val} 超过 5000"

    # 确认不应有 le=20000
    assert 'le=20000' not in src.split("page_size")[1].split("\n")[0], (
        "page_size 行不应再有 le=20000"
    )
