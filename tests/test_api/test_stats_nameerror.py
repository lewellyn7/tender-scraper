#!/usr/bin/env python3
"""stats.py NameError regression test (2026-06-27)

Bug: _pg_pool vs _pool 变量名不一致 → /api/stats 每次请求 NameError
Fix: 全部统一为 _pg_pool
"""
import ast
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


class TestStatsNameErrorRegression(unittest.TestCase):
    """测试 _get_pg_conn 函数内部变量名一致性"""
    
    def setUp(self):
        stats_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "app", "api", "routes", "stats.py"
        )
        with open(stats_path) as f:
            self.source = f.read()
    
    def _find_func_body(self, name):
        """提取指定函数源码 (字符串)"""
        tree = ast.parse(self.source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return ast.get_source_segment(self.source, node)
        return None
    
    def test_get_pg_conn_uses_consistent_variable_name(self):
        """读 stats.py 源码, 验证 _pool 变量已统一为 _pg_pool (AST 级别)"""
        func_body = self._find_func_body("_get_pg_conn")
        self.assertIsNotNone(func_body, "_get_pg_conn 函数未找到")
        
        # 解析函数体 AST
        tree = ast.parse(func_body)
        func_node = tree.body[0]
        
        # 收集所有 Name 节点
        names_used = set()
        for node in ast.walk(func_node):
            if isinstance(node, ast.Name):
                names_used.add(node.id)
            elif isinstance(node, ast.Attribute):
                # attr access 不算 Name, 但需要确认是 ._pool 还是 .getconn
                pass
        
        # 关键断言: 函数体内不应使用未限定的 _pool (只能 _pg_pool 或字符串 "_pool")
        # ast.Name 涵盖所有变量引用
        self.assertNotIn(
            "_pool", names_used,
            f"_get_pg_conn 函数体内不应使用未限定的 _pool 变量, 找到: {names_used}"
        )
        self.assertIn(
            "_pg_pool", names_used,
            f"_get_pg_conn 函数体应使用 _pg_pool, 找到的 names: {names_used}"
        )
    
    def test_compile_check(self):
        """stats.py 文件能正常编译"""
        try:
            compile(self.source, "stats.py", "exec")
        except SyntaxError as e:
            self.fail(f"stats.py 编译失败: {e}")


if __name__ == "__main__":
    unittest.main()