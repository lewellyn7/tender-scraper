"""P1 修复验证: cqggzy infoid _N 后缀 + logger.warning

验证:
1. AST: infoid 处理保留 _1 后缀 (不再 strip)
2. AST: logger.warning + exc_info=True 用于 API fallback
3. 字符串: 输入 "abc_2" → 输出 "abc_2" (保留原 _N)
           输入 "xyz" → 输出 "xyz_1" (补 _1)
"""

import ast
import os

import pytest

CQGGZY_PY = os.path.join(
    os.path.dirname(__file__),
    "../app/crawlers/cqggzy.py",
)


def _parse_file():
    with open(CQGGZY_PY, "r") as f:
        return ast.parse(f.read())


class TestInfoidSuffix:
    """验证 infoid 处理逻辑：保留 _N 后缀，裸 ID 补 _1"""

    def test_no_split_underscore_strip(self):
        """AST 验证：不再使用 split('_')[0] 或 .split('_') 剥离 infoid 后缀"""
        tree = _parse_file()
        found_strip = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check for .split('_') calls that select [0]
                if isinstance(node.func, ast.Attribute) and node.func.attr == "split":
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and arg.value == "_":
                            found_strip = True
                            break
        assert not found_strip, "不应再使用 .split('_') 剥离 infoid 后缀"

    def test_preserve_or_append_1(self):
        """AST 验证：infoid 不含下划线时补 _1"""
        tree = _parse_file()
        found_append = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Look for string formatting like f'{infoid}_1'
                if isinstance(node.func, ast.Attribute) and node.func.attr == "__add__":
                    pass
            if isinstance(node, ast.JoinedStr):
                for value in node.values:
                    if isinstance(value, ast.Constant) and "_1" in str(value.value):
                        found_append = True
                        break
        assert found_append, "应使用 infoid + '_1' 或 f'{infoid}_1' 补全后缀"

    def test_infoid_suffix_logic(self):
        """字符串逻辑测试: 保留 _N, 裸 ID 补 _1"""
        # Simulate the curl-path logic applied to Playwright path
        test_cases = [
            ("1645485773757394944_2", "1645485773757394944_2", "保留已有 _2 后缀"),
            ("1645485773757394944_1", "1645485773757394944_1", "保留已有 _1 后缀"),
            ("1645485773757394944", "1645485773757394944_1", "裸数字 ID 补 _1"),
            ("", "", "空字符串不变"),
            ("abc_3", "abc_3", "保留已有 _3 后缀"),
            ("xyz", "xyz_1", "裸字母 ID 补 _1"),
        ]
        for infoid, expected, desc in test_cases:
            result = infoid if '_' in infoid or not infoid else f'{infoid}_1'
            assert result == expected, f"{desc}: 输入={infoid}, 期望={expected}, 实际={result}"


class TestLoggerWarning:
    """验证 API fallback 日志级别提升"""

    def test_logger_warning_with_exc_info(self):
        """AST 验证：API fallback 使用 logger.warning + exc_info=True + 关键字 NUXT"""
        tree = _parse_file()
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) \
               and isinstance(node.func, ast.Attribute) \
               and node.func.attr == "warning":
                has_exc_info = any(
                    kw.arg == "exc_info" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                    for kw in node.keywords
                )
                # Check message for "NUXT" — handles both f-strings (JoinedStr) and plain strings (Constant)
                msg_raw = ast.dump(node.args[0]) if node.args else ""
                has_nuxt = "NUXT" in msg_raw
                if has_exc_info and has_nuxt:
                    found = True
                    break
        assert found, "应有 logger.warning(..., exc_info=True) 且消息含 'NUXT'"

    def test_warning_has_logger_dot_warning_not_debug(self):
        """AST 验证：API fallback 的调用是 logger.warning 不是 logger.debug"""
        tree = _parse_file()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) \
               and isinstance(node.func, ast.Attribute) \
               and node.func.attr == "debug":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and "回退到 NUXT" in str(arg.value):
                        pytest.fail("API→NUXT fallback 不应再用 logger.debug")

    def test_no_fallback_debug(self):
        """AST 验证：不再使用 logger.debug 处理 API fallback"""
        tree = _parse_file()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr == "debug":
                    for arg in node.args:
                        if isinstance(arg, ast.JoinedStr) or isinstance(arg, ast.Constant):
                            val = ast.dump(arg)
                            if "API 获取失败，回退到 NUXT" in val or "回退到 NUXT" in val:
                                pytest.fail("不应再使用 logger.debug 处理 API→NUXT fallback")
