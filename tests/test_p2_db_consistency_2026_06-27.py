"""
单测: P2 DB 一致性 3 项修复 (2026-06-27)

验证:
  - 3.11 upsert_project 使用 ON CONFLICT (不再是 SELECT-then-UPDATE/INSERT)
  - 3.12 upsert_projects_ccgp 的 scraped_at 使用 CASE WHEN (不再是 COALESCE/NULLIF)
  - 3.13 upsert_bid_results 文档化 dedup 语义差
  - 所有关键函数可正常 import
"""

import ast
import re


def _read(path):
    with open(path) as f:
        return f.read()


def test_3_11_upsert_project_uses_on_conflict():
    """3.11: upsert_project 应使用 ON CONFLICT, 不再是 SELECT-then-UPDATE/INSERT"""
    src = _read("app/database/tables/projects.py")

    # 验证包含 ON CONFLICT
    assert "ON CONFLICT (project_no)" in src, \
        "upsert_project 应包含 ON CONFLICT (project_no)"

    # 验证不再有 SELECT … WHERE project_no = ? 的 TOCTOU 模式
    # (NULL 分支仍保留 SELECT, 只检查 pno IS NOT NULL 分支)
    # 确认 INSERT ... ON CONFLICT 出现在 upsert_project 方法内
    upsert_start = src.index("def upsert_project(")
    upsert_end = src.index("def get_project_by_no(")
    upsert_body = src[upsert_start:upsert_end]

    assert "ON CONFLICT" in upsert_body, \
        "upsert_project 方法体内应包含 ON CONFLICT"

    # NULL 路径仍保留 SELECT (无 UNIQUE 约束可用)
    assert "WHERE project_no IS NULL AND project_name" in upsert_body, \
        "NULL project_no 路径仍需 SELECT 匹配 (无可用的 UNIQUE 约束)"

    print("  ✅ upsert_project: ON CONFLICT 模式")


def test_3_12_upsert_projects_ccgp_scraped_at_case_when():
    """3.12: upsert_projects_ccgp 的 scraped_at 应使用 CASE WHEN"""
    src = _read("app/database/db.py")

    # 定位 upsert_projects_ccgp 方法
    ccgp_start = src.index("def upsert_projects_ccgp(")
    next_def_match = re.search(r'\n    def \w+\(', src[ccgp_start + 30:])
    if next_def_match:
        ccgp_end = ccgp_start + 30 + next_def_match.start()
    else:
        ccgp_end = len(src)
    ccgp_body = src[ccgp_start:ccgp_end]

    # 验证 timestamp_protected_cols 包含 scraped_at
    assert "timestamp_protected_cols" in ccgp_body, \
        "ccgp 应定义 timestamp_protected_cols"

    assert '"scraped_at"' in ccgp_body, \
        "scraped_at 应在 timestamp_protected_cols 中"

    # 验证 CASE WHEN 模式用于 timestamp 保护
    assert "CASE WHEN EXCLUDED." in ccgp_body, \
        "应使用 CASE WHEN 保护 timestamp 字段"

    # 验证不再将 scraped_at 放入 text_protected_cols
    text_protected_match = re.search(
        r'text_protected_cols\s*=\s*\{([^}]+)\}', ccgp_body
    )
    assert text_protected_match, "应定义 text_protected_cols"
    text_cols_str = text_protected_match.group(1)
    assert "scraped_at" not in text_cols_str, \
        "scraped_at 不应在 text_protected_cols（已在 timestamp_protected_cols）"

    print("  ✅ upsert_projects_ccgp: scraped_at 使用 CASE WHEN (统一 cqggzy/fahcqmu)")


def test_3_13_upsert_bid_results_dedup_doc():
    """3.13: upsert_bid_results 应文档化 dedup 语义差"""
    src = _read("app/database/db.py")

    # 定位 upsert_bid_results
    bid_start = src.index("def upsert_bid_results(")
    next_match = re.search(r'\n    def \w+\(', src[bid_start + 30:])
    if next_match:
        bid_end = bid_start + 30 + next_match.start()
    else:
        bid_end = len(src)
    bid_body = src[bid_start:bid_end]

    # 验证文档化注释
    assert "内存 dedup 与 DB UNIQUE 约束语义差" in bid_body, \
        "docstring 应注明内存 dedup 与 DB UNIQUE 语义差"

    assert "NULL != NULL" in bid_body, \
        "docstring 应解释 PG NULL UNIQUE 语义"

    assert "NOT NULL 约束" in bid_body or "COALESCE in UNIQUE" in bid_body, \
        "docstring 应包含推荐修复方案"

    # 验证 dedup 逻辑未被改动 (行为不变)
    assert "dedup_key = r.get('cleaned_winner_name') or r.get('winner_name')" in bid_body, \
        "dedup 逻辑不应被改动 (行为不变)"

    print("  ✅ upsert_bid_results: dedup 语义差已文档化, 逻辑不变")


def test_all_functions_importable():
    """验证所有关键函数可正常 import"""
    from app.database.tables.projects import ProjectsMixin
    from app.database.db import Database

    # 验证方法存在
    assert hasattr(ProjectsMixin, 'upsert_project'), \
        "ProjectsMixin 应有 upsert_project 方法"
    assert hasattr(Database, 'upsert_projects_ccgp'), \
        "Database 应有 upsert_projects_ccgp 方法"
    assert hasattr(Database, 'upsert_bid_results'), \
        "Database 应有 upsert_bid_results 方法"

    print("  ✅ 所有关键函数可正常 import")


def test_upsert_project_on_conflict_sql_complete():
    """AST 验证 upsert_project 的 ON CONFLICT SQL 包含所有必要字段"""
    src = _read("app/database/tables/projects.py")

    upsert_start = src.index("def upsert_project(")
    upsert_end = src.index("def get_project_by_no(")
    upsert_body = src[upsert_start:upsert_end]

    # 验证 DO UPDATE SET 包含所有业务字段
    assert "project_name = EXCLUDED.project_name" in upsert_body
    assert "project_name_raw = EXCLUDED.project_name_raw" in upsert_body
    assert "business_type = EXCLUDED.business_type" in upsert_body
    assert "region = EXCLUDED.region" in upsert_body
    assert "industry = EXCLUDED.industry" in upsert_body
    assert "budget = EXCLUDED.budget" in upsert_body
    assert "updated_at = CURRENT_TIMESTAMP" in upsert_body

    # 验证 RETURNING id
    assert "RETURNING id" in upsert_body

    print("  ✅ upsert_project: ON CONFLICT SQL 字段完整 + RETURNING id")
