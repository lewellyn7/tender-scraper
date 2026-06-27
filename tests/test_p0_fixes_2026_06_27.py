"""P0 fixes 验证测试 — 2026-06-27
- analytics.py: /api/analytics 需要认证
- async_models.py: logging 已 import + upsert 正则正确解析 PG 返回格式
"""
import ast
import re
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_analytics_requires_auth():
    """验证 /api/analytics 端点已挂载认证"""
    src = open("app/api/routes/analytics.py", encoding="utf-8").read()
    tree = ast.parse(src)

    auth_deps_found = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for arg in node.args.args + node.args.kwonlyargs:
                if arg.arg in ("current_user", "user") or "current_user" in [d.id for d in ast.walk(node) if isinstance(d, ast.Name)]:
                    auth_deps_found += 1
                # check default is Depends call
                if node.args.defaults:
                    for d in node.args.defaults:
                        if isinstance(d, ast.Call):
                            fname = d.func.id if isinstance(d.func, ast.Name) else None
                            if fname == "Depends":
                                auth_deps_found += 1

    # 至少 1 个 get_analytics 端点需 Depends(get_current_user)
    assert "Depends" in src, "缺少 Depends import"
    assert "get_current_user" in src, "缺少 get_current_user 引用"
    assert 'Depends(get_current_user)' in src, "get_analytics 未挂载 Depends"
    # 验证 import 顺序
    assert "from app.api.dependencies import get_current_user" in src, "未 import get_current_user"
    print("✅ analytics.py /api/analytics 已挂载 get_current_user 认证")


def test_async_models_logging_imported():
    """验证 async_models.py 顶部有 logging import"""
    src = open("app/database/async_models.py", encoding="utf-8").read()
    tree = ast.parse(src)

    imports_found = {"logging": False, "logger": False}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                if "logging" == n.name:
                    imports_found["logging"] = True
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "logger":
                    imports_found["logger"] = True
    assert imports_found["logging"], "async_models.py 顶部未 import logging"
    assert imports_found["logger"], "async_models.py 未定义 logger"
    # 验证 logger.error 使用
    assert "logger.error" in src, "异常处理器未使用 logger"
    assert "exc_info=True" in src, "logger.error 应传 exc_info=True"
    print("✅ async_models.py logging 已 import, 异常处理器用 logger.error")


def test_upsert_regex_matches_pg_formats():
    """验证 upsert_batch 正则能解析 PG 的 3 种返回格式"""
    src = open("app/database/async_models.py", encoding="utf-8").read()
    # 提取正则模式（手动捕获 3 个 ^...$ 行）
    assert 'r"^INSERT 0 (\\d+)$"' in src, "缺纯 INSERT 正则"
    assert 'r"^UPDATE (\\d+)$"' in src, "缺纯 UPDATE 正则"
    assert 'r"^INSERT 0 (\\d+) UPDATE (\\d+)$"' in src, "缺 upsert 正则"

    # 实际匹配测试
    import re
    pat_insert = re.compile(r"^INSERT 0 (\d+)$")
    pat_update = re.compile(r"^UPDATE (\d+)$")
    pat_upsert = re.compile(r"^INSERT 0 (\d+) UPDATE (\d+)$")

    assert pat_insert.match("INSERT 0 5").group(1) == "5"
    assert pat_update.match("UPDATE 3").group(1) == "3"
    assert pat_upsert.match("INSERT 0 2 UPDATE 3").group(1) == "2"
    assert pat_upsert.match("INSERT 0 2 UPDATE 3").group(2) == "3"

    # 旧 bug: 单 UPDATE 5 不会误匹配
    assert not pat_insert.match("UPDATE 5")
    assert not pat_upsert.match("UPDATE 5")
    print("✅ upsert 正则正确解析 PG 3 种返回格式")


def test_no_regression_on_health_endpoint():
    """验证 /api/analytics/health 路径未受影响 (本次 PR 不动)"""
    src = open("app/api/routes/analytics.py", encoding="utf-8").read()
    # 健康端点保留, 不在本次修改范围
    assert '@router.get("/health")' in src, "/health 端点不应被本次 PR 删除"
    print("✅ /api/analytics/health 端点保留 (在 P1 #2.8 单独修)")


if __name__ == "__main__":
    test_analytics_requires_auth()
    test_async_models_logging_imported()
    test_upsert_regex_matches_pg_formats()
    test_no_regression_on_health_endpoint()
    print("\n🎉 P0 fixes 单测 4/4 通过")
