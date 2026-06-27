"""
P2 修复验证 — 调度+工具 5 项

测试:
  3.14 _compute_health_score 公式改为 0.5 + sr * 0.5
  3.15 _get_redis() 加 threading.Lock
  3.16 _fallback dict 加 RLock
  3.17 pipeline.py 第一遍 source-balanced 计算被删除
  3.18 _parse_redis_url 抽到 app/utils/redis_url.py
"""

import ast
import os
import sys
import unittest

WORKTREE = os.environ.get("WORKTREE", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if WORKTREE not in sys.path:
    sys.path.insert(0, WORKTREE)


class TestP2HarvestUtils(unittest.TestCase):
    """3.14-3.18 P2 fix verification"""

    # ── 3.14 health score formula ──────────────────────────
    def test_3_14_health_score_formula(self):
        """_compute_health_score 使用 base_score = 0.5 + success_rate * 0.5"""
        path = os.path.join(WORKTREE, "app", "core", "harvest", "predictive_anomaly.py")
        with open(path) as f:
            source = f.read()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_compute_health_score":
                # Check: 函数体内第一个赋值语句包含 0.5 + ... * 0.5
                found = False
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            if isinstance(target, ast.Name) and target.id == "base_score":
                                val = ast.dump(stmt.value)
                                # 应该包含 BinOp Add 且操作数含 Num(0.5)
                                self.assertIn("Add", val, f"base_score should use +: {val}")
                                self.assertIn("0.5", val, f"base_score should contain 0.5: {val}")
                                self.assertIn("Mult", val, f"base_score should contain *: {val}")
                                found = True
                self.assertTrue(found, "base_score assignment not found in _compute_health_score")
                return
        self.fail("_compute_health_score function not found")

    def test_3_14_no_old_formula(self):
        """确认旧公式 success_rate * 0.4 不再存在"""
        path = os.path.join(WORKTREE, "app", "core", "harvest", "predictive_anomaly.py")
        with open(path) as f:
            source = f.read()
        self.assertNotIn("base_score = success_rate_7d * 0.4", source,
                         "Old formula still present")

    # ── 3.15 _get_redis lock ───────────────────────────────
    def test_3_15_redis_lock_in_init(self):
        """DataCache.__init__ 包含 self._redis_lock = threading.Lock()"""
        path = os.path.join(WORKTREE, "app", "core", "harvest", "data_cache.py")
        with open(path) as f:
            source = f.read()
        self.assertIn("self._redis_lock", source,
                      "DataCache.__init__ missing _redis_lock")

    def test_3_15_get_redis_uses_lock(self):
        """_get_redis 方法体包含 with self._redis_lock:"""
        path = os.path.join(WORKTREE, "app", "core", "harvest", "data_cache.py")
        with open(path) as f:
            source = f.read()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_get_redis":
                found = False
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.With):
                        for item in stmt.items:
                            ce = item.context_expr
                            if isinstance(ce, ast.Attribute) and "redis_lock" in ast.dump(ce):
                                found = True
                self.assertTrue(found, "_get_redis missing 'with self._redis_lock'")
                return
        self.fail("_get_redis function not found")

    # ── 3.16 cache_manager fallback lock ───────────────────
    def test_3_16_fallback_lock_declared(self):
        """RedisManager 类包含 _fallback_lock = threading.RLock()"""
        path = os.path.join(WORKTREE, "app", "core", "harvest", "cache_manager.py")
        with open(path) as f:
            source = f.read()
        self.assertIn("_fallback_lock", source,
                      "RedisManager missing _fallback_lock")
        self.assertIn("RLock", source,
                      "RedisManager missing RLock reference")

    def test_3_16_get_uses_lock(self):
        """RedisManager.get fallback 路径使用 with cls._fallback_lock"""
        path = os.path.join(WORKTREE, "app", "core", "harvest", "cache_manager.py")
        with open(path) as f:
            source = f.read()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get":
                found = False
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.With):
                        for item in stmt.items:
                            ce = item.context_expr
                            if isinstance(ce, ast.Attribute) and "fallback_lock" in ast.dump(ce):
                                found = True
                self.assertTrue(found, "get fallback path missing 'with cls._fallback_lock'")
                return
        self.fail("get function not found")

    def test_3_16_set_uses_lock(self):
        """RedisManager.set fallback 路径使用 with cls._fallback_lock"""
        path = os.path.join(WORKTREE, "app", "core", "harvest", "cache_manager.py")
        with open(path) as f:
            source = f.read()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "set":
                found = False
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.With):
                        for item in stmt.items:
                            ce = item.context_expr
                            if isinstance(ce, ast.Attribute) and "fallback_lock" in ast.dump(ce):
                                found = True
                self.assertTrue(found, "set fallback path missing 'with cls._fallback_lock'")
                return
        self.fail("set function not found")

    # ── 3.17 pipeline source-balanced dedup ────────────────
    def test_3_17_no_duplicated_by_source(self):
        """pipeline.py 只包含一个 by_source defaultdict 构建"""
        path = os.path.join(WORKTREE, "app", "core", "harvest", "pipeline.py")
        with open(path) as f:
            source = f.read()
        # by_source_sorted 已被删除
        self.assertNotIn("by_source_sorted", source)
        # detail_items_new 已被删除
        self.assertNotIn("detail_items_new", source)
        # by_source 应该只出现有限次数 (import defaultdict + by_source[src].append + sources = list(by_source.keys()))
        count = source.count("by_source")
        self.assertLess(count, 8, f"by_source appears {count} times, should be <8 after dedup")

    def test_3_17_single_source_balanced_comment(self):
        """pipeline.py 包含 '仅计算一遍' 注释"""
        path = os.path.join(WORKTREE, "app", "core", "harvest", "pipeline.py")
        with open(path) as f:
            source = f.read()
        self.assertIn("仅计算一遍", source)

    # ── 3.18 parse_redis_url extraction ────────────────────
    def test_3_18_redis_url_module_exists(self):
        """app/utils/redis_url.py 存在且包含 parse_redis_url"""
        path = os.path.join(WORKTREE, "app", "utils", "redis_url.py")
        self.assertTrue(os.path.exists(path), "app/utils/redis_url.py not found")
        with open(path) as f:
            source = f.read()
        tree = ast.parse(source)
        funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        self.assertIn("parse_redis_url", funcs,
                      "parse_redis_url not found in redis_url.py")

    def test_3_18_scheduler_no_def(self):
        """scheduler.py 不再定义 _parse_redis_url, 改为 import"""
        path = os.path.join(WORKTREE, "app", "scheduler.py")
        with open(path) as f:
            source = f.read()
        tree = ast.parse(source)
        funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        self.assertNotIn("_parse_redis_url", funcs,
                         "scheduler.py should not define _parse_redis_url")
        # 确认 import
        self.assertIn("from app.utils.redis_url import parse_redis_url as _parse_redis_url",
                      source, "scheduler.py missing import")

    def test_3_18_collector_no_def(self):
        """collector.py 不再定义 _parse_redis_url, 改为 import"""
        path = os.path.join(WORKTREE, "app", "workers", "collector.py")
        with open(path) as f:
            source = f.read()
        tree = ast.parse(source)
        funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        self.assertNotIn("_parse_redis_url", funcs,
                         "collector.py should not define _parse_redis_url")
        # 确认 import
        self.assertIn("from app.utils.redis_url import parse_redis_url as _parse_redis_url",
                      source, "collector.py missing import")

    def test_3_18_parse_redis_url_returns_correct_structure(self):
        """parse_redis_url 返回正确结构"""
        from app.utils.redis_url import parse_redis_url
        result = parse_redis_url("redis://:mypass@host:1234/5")
        self.assertEqual(result["host"], "host")
        self.assertEqual(result["port"], 1234)
        self.assertEqual(result["db"], 5)
        self.assertEqual(result["password"], "mypass")

    def test_3_18_parse_redis_url_defaults(self):
        """parse_redis_url 默认值"""
        from app.utils.redis_url import parse_redis_url
        result = parse_redis_url("redis://localhost:6379")
        self.assertEqual(result["host"], "localhost")
        self.assertEqual(result["port"], 6379)
        self.assertEqual(result["db"], 0)
        self.assertIsNone(result["password"])


if __name__ == "__main__":
    unittest.main()
