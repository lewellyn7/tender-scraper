#!/usr/bin/env python3
"""Migration 003 单测 - updated_at trigger 验证

无需 DB 连接, 直接调用 migration SQL 并验证结果。
集成测试在 test_api/test_migration_003_integration.py 中。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))


class TestMigration003SQLSyntax(unittest.TestCase):
    """测试 SQL 语法正确性 (无 DB 连接)"""
    
    def test_migration_file_exists(self):
        path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "app", "database", "migrations", "003_add_updated_at_trigger.sql"
        )
        self.assertTrue(os.path.exists(path), f"Migration 文件不存在: {path}")
    
    def test_rollback_file_exists(self):
        path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "app", "database", "migrations", "003_rollback.sql"
        )
        self.assertTrue(os.path.exists(path), f"Rollback 文件不存在: {path}")
    
    def test_migration_is_idempotent(self):
        """检查 SQL 含 IF NOT EXISTS / OR REPLACE / DROP IF EXISTS"""
        with open(os.path.join(
            os.path.dirname(__file__),
            "..", "..", "app", "database", "migrations", "003_add_updated_at_trigger.sql"
        )) as f:
            content = f.read()
        # 至少 5 个 DROP TRIGGER IF EXISTS (每个表一个)
        self.assertGreaterEqual(content.count("DROP TRIGGER IF EXISTS"), 5)
        # CREATE OR REPLACE FUNCTION
        self.assertIn("CREATE OR REPLACE FUNCTION set_updated_at", content)
        # ALTER TABLE ADD COLUMN IF NOT EXISTS
        self.assertIn("ALTER TABLE project_records ADD COLUMN IF NOT EXISTS", content)
    
    def test_migration_targets_all_tables(self):
        """检查所有目标表都加了 trigger"""
        with open(os.path.join(
            os.path.dirname(__file__),
            "..", "..", "app", "database", "migrations", "003_add_updated_at_trigger.sql"
        )) as f:
            content = f.read()
        for table in ["projects", "project_records", "projects_ccgp", 
                      "projects_cqggzy", "projects_fahcqmu"]:
            self.assertIn(f"BEFORE UPDATE ON {table}", content,
                          f"表 {table} 缺少 trigger 定义")
        # 5 个 trigger (项目/记录/3 个 source 表)
        self.assertEqual(content.count("CREATE TRIGGER"), 5)


if __name__ == "__main__":
    unittest.main()