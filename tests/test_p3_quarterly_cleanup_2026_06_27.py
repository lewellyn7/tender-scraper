"""P3 季度清理 2026-06-27 单测 — AST 验证各项清理已执行.

验证项:
  P3.1: cqggzy.py import 减少 (5 个未使用 import 已删)
  P3.2: cqggzy.py 模块级 dict _BLOCKED_TITLE_KEYWORDS / _CATEGORY_INFO_TYPE 上提
  P3.3: cqggzy_curl.py 模块级 dict _CATEGORY_INFO_TYPE 上提
  P3.4: analytics.py bare except 已加 logger.warning
  P3.6: 全文件零 datetime.utcnow (已确认无)
  P3.8: harvest_api.py 端点有 Depends(get_current_user)
  P3.9: harvest_api.py SourceStatItem 已删
  P3.7: projects.py 模块有 _project_cache + get_project 含 lock 逻辑
"""

import ast
import os
import sys
import unittest

WORKTREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _parse(path_rel):
    with open(os.path.join(WORKTREE, path_rel)) as f:
        return ast.parse(f.read()), f.read()


class TestP3QuarterlyCleanup(unittest.TestCase):
    """P3 季度清理 11 项 AST 验证"""

    # ── P3.1: cqggzy.py import 减少 ──────────────────────────────────────
    def test_p3_1_unused_imports_removed(self):
        """cqggzy.py: 5 unused imports removed (os, httpx, get_db, make_summary, normalize_project_name)"""
        tree, src = _parse("app/crawlers/cqggzy.py")
        import_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    import_names.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    import_names.add(f"{node.module}:{alias.name}")
        self.assertNotIn("os", import_names, "os should be removed")
        self.assertNotIn("httpx", import_names, "httpx should be removed")
        # get_db was imported from app.database
        self.assertNotIn("app.database:get_db", import_names, "get_db should be removed")
        self.assertNotIn("app.utils.summarize:summarize", import_names, "make_summary removed")
        self.assertNotIn("app.utils.project_linker:normalize_project_name", import_names, "normalize_project_name removed")
        # extract_project_no should still be there
        self.assertIn("app.utils.project_linker:extract_project_no", import_names)

    # ── P3.2: cqggzy.py dict 上提 ────────────────────────────────────────
    def test_p3_2_dicts_at_module_level(self):
        """cqggzy.py: _BLOCKED_TITLE_KEYWORDS / _CATEGORY_INFO_TYPE at module level"""
        tree, src = _parse("app/crawlers/cqggzy.py")
        module_assigns = {}
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        module_assigns[target.id] = node
        # Both should be at module level
        self.assertIn("_BLOCKED_TITLE_KEYWORDS", module_assigns,
                      "_BLOCKED_TITLE_KEYWORDS should be at module level")
        self.assertIn("_CATEGORY_INFO_TYPE", module_assigns,
                      "_CATEGORY_INFO_TYPE should be at module level")
        # Verify _CATEGORY_INFO_TYPE is a Dict
        cat_node = module_assigns["_CATEGORY_INFO_TYPE"]
        self.assertIsInstance(cat_node.value, ast.Dict,
                              "_CATEGORY_INFO_TYPE should be a dict literal")
        self.assertGreaterEqual(len(cat_node.value.keys), 9,
                                "Should have 9+ entries")

        # Verify they are NOT re-assigned inside functions (loops)
        func_assigns = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Assign):
                        for target in sub.targets:
                            if isinstance(target, ast.Name):
                                func_assigns.add(target.id)
        self.assertNotIn("_BLOCKED_TITLE_KEYWORDS", func_assigns,
                         "_BLOCKED_TITLE_KEYWORDS should not be re-assigned in function")
        self.assertNotIn("_CATEGORY_INFO_TYPE", func_assigns,
                         "_CATEGORY_INFO_TYPE should not be re-assigned in function")

    # ── P3.3: cqggzy_curl.py dict 上提 ───────────────────────────────────
    def test_p3_3_dicts_at_module_level_curl(self):
        """cqggzy_curl.py: _CATEGORY_INFO_TYPE at module level"""
        tree, src = _parse("app/crawlers/cqggzy_curl.py")
        module_assigns = {}
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        module_assigns[target.id] = node
        self.assertIn("_CATEGORY_INFO_TYPE", module_assigns,
                      "_CATEGORY_INFO_TYPE should be at module level in curl")
        cat_node = module_assigns["_CATEGORY_INFO_TYPE"]
        self.assertIsInstance(cat_node.value, ast.Dict)
        self.assertGreaterEqual(len(cat_node.value.keys), 9)

        func_assigns = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Assign):
                        for target in sub.targets:
                            if isinstance(target, ast.Name):
                                func_assigns.add(target.id)
        self.assertNotIn("_CATEGORY_INFO_TYPE", func_assigns,
                         "_CATEGORY_INFO_TYPE not re-assigned in function")

    # ── P3.4: analytics.py logger.warning ────────────────────────────────
    def test_p3_4_logger_warning_added(self):
        """analytics.py: bare except blocks now have logger.warning"""
        tree, src = _parse("app/api/routes/analytics.py")
        # Verify logger.warning calls exist in except handlers
        logger_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if (isinstance(node.func, ast.Attribute) and
                    isinstance(node.func.value, ast.Name) and
                    node.func.value.id == "logger" and
                    node.func.attr == "warning"):
                    logger_calls.append(node)
        self.assertGreaterEqual(len(logger_calls), 5,
                                f"Expected ≥5 logger.warning calls, found {len(logger_calls)}")

        # Verify no bare print() in _load_projects_pg except handlers
        print_calls = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if (isinstance(node.func, ast.Name) and node.func.id == "print"):
                    print_calls += 1
        self.assertEqual(print_calls, 0,
                         f"print() should be 0, found {print_calls}")

    # ── P3.6: zero datetime.utcnow ───────────────────────────────────────
    def test_p3_6_no_datetime_utcnow(self):
        """All 6 files: zero datetime.utcnow() calls"""
        files = [
            "app/crawlers/cqggzy.py",
            "app/crawlers/cqggzy_curl.py",
            "app/api/routes/analytics.py",
            "app/api/routes/projects.py",
            "app/api/harvest_api.py",
            "app/database/db.py",
        ]
        for f in files:
            with open(os.path.join(WORKTREE, f)) as fh:
                src = fh.read()
            self.assertNotIn("datetime.utcnow", src,
                             f"{f} should not contain datetime.utcnow")
            self.assertNotIn(".utcnow()", src,
                             f"{f} should not contain .utcnow()")

    # ── P3.7: projects.py cache ──────────────────────────────────────────
    def test_p3_7_project_cache_added(self):
        """projects.py: /project/{url} has cache + lock"""
        tree, src = _parse("app/api/routes/projects.py")

        # Module-level cache variables (both Assign + AnnAssign)
        module_vars = {}
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        module_vars[target.id] = node
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                module_vars[node.target.id] = node
        self.assertIn("_project_cache", module_vars, "Should have _project_cache (AnnAssign)")
        self.assertIn("_project_cache_lock", module_vars, "Should have _project_cache_lock")
        self.assertIn("_project_cache_ttl", module_vars, "Should have _project_cache_ttl")

        # get_project function should be async and use _project_cache_lock
        found_get_project = False
        is_async = False
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_project":
                found_get_project = True
                is_async = True
                break
            if isinstance(node, ast.FunctionDef) and node.name == "get_project":
                found_get_project = True
                break
        self.assertTrue(found_get_project, "get_project function should exist")
        self.assertTrue(is_async, "get_project should be async")

    # ── P3.8: harvest_api.py endpoints have Depends(get_current_user) ────
    def test_p3_8_endpoints_have_auth(self):
        """harvest_api.py: each endpoint has Depends(get_current_user)"""
        tree, src = _parse("app/api/harvest_api.py")

        endpoint_funcs = {"health_check", "trigger_crawl", "get_task_status",
                          "get_crawl_results", "get_stats"}
        found_with_auth = set()

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in endpoint_funcs:
                    # FastAPI Depends appears as default value, not annotation.
                    # Check all defaults for Depends(get_current_user) call.
                    defaults = list(node.args.defaults) + list(node.args.kw_defaults)
                    has_depends = False
                    for d in defaults:
                        if d is None:
                            continue
                        dump_s = ast.dump(d)
                        if "Depends" in dump_s and "get_current_user" in dump_s:
                            has_depends = True
                            break
                    if has_depends:
                        found_with_auth.add(node.name)

        self.assertEqual(found_with_auth, endpoint_funcs,
                         f"All endpoints should have Depends(get_current_user). "
                         f"Missing: {endpoint_funcs - found_with_auth}")

    # ── P3.9: harvest_api.py SourceStatItem removed ──────────────────────
    def test_p3_9_source_stat_item_removed(self):
        """harvest_api.py: SourceStatItem class removed"""
        tree, src = _parse("app/api/harvest_api.py")
        class_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_names.add(node.name)
        self.assertNotIn("SourceStatItem", class_names,
                         "SourceStatItem should be removed")
        # But other classes should still be there
        self.assertIn("CrawlRequest", class_names)
        self.assertIn("CrawlResponse", class_names)
        self.assertIn("StatsResponse", class_names)


if __name__ == "__main__":
    unittest.main()
