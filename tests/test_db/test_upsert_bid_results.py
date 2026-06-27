"""
test_upsert_bid_results.py — 验证 upsert_bid_results SQL + 参数

PR #40 (去重) 改了 bid_results UNIQUE 约束: winner_name → cleaned_winner_name.
PR #41 (清洗) 让 bid_parser 写入 cleaned_winner_name.
但 db.py:586 upsert_bid_results 仍用旧的 winner_name 列做 ON CONFLICT →
"there is no unique or exclusion constraint matching" 错误, 每天 0 条入.

修复 (2026-06-27):
  1. values tuple 加 cleaned_winner_name 字段
  2. INSERT 字段加 cleaned_winner_name
  3. ON CONFLICT 列改 cleaned_winner_name
  4. DO UPDATE SET 保护 cleaned_winner_name (COALESCE 防空值覆盖)
"""
import sys
import os
import re
import inspect

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


def _extract_insert_sql():
    """从 db.py 提取 upsert_bid_results 实际拼的 SQL 字符串."""
    from app.database import db as db_module
    src = inspect.getsource(db_module.Database.upsert_bid_results)
    # 找到三引号 SQL 块
    m = re.search(r'insert_sql\s*=\s*"""(.+?)"""', src, re.DOTALL)
    assert m, "未找到 insert_sql 三引号字符串"
    return m.group(1)


def test_sql_uses_cleaned_winner_name_in_on_conflict():
    """ON CONFLICT 必须用 cleaned_winner_name, 不然 6-27 修复前 bug 又复发."""
    sql = _extract_insert_sql()
    assert "ON CONFLICT (source, project_id, package_no, cleaned_winner_name)" in sql, (
        f"ON CONFLICT 没用 cleaned_winner_name!\n--- SQL ---\n{sql}"
    )
    # 反向断言: 旧的 winner_name 不应再出现在 ON CONFLICT 子句
    # (DO UPDATE SET winner_name=EXCLUDED.winner_name 是 OK 的)
    on_conflict_match = re.search(r'ON CONFLICT\s*\(([^)]+)\)', sql)
    assert on_conflict_match
    cols = on_conflict_match.group(1)
    assert 'winner_name' not in cols.replace(' ', '').split(','), (
        f"ON CONFLICT 列仍含 winner_name (bug 已复发): {cols}"
    )


def test_sql_inserts_cleaned_winner_name_column():
    """INSERT 字段列表必须含 cleaned_winner_name, 不然 rows['cleaned_winner_name'] 被丢弃."""
    sql = _extract_insert_sql()
    # 简单解析: INSERT INTO bid_results ( ... ) 之间的列名
    m = re.search(r'INSERT INTO bid_results\s*\(([^)]+)\)', sql, re.DOTALL)
    assert m, "未找到 INSERT 列定义"
    cols = [c.strip() for c in m.group(1).split(',')]
    assert 'cleaned_winner_name' in cols, f"INSERT 列缺 cleaned_winner_name: {cols}"


def test_sql_protects_existing_cleaned_winner_name():
    """DO UPDATE SET 里的 cleaned_winner_name 必须用 COALESCE 保护, 不然空值覆盖手工填值."""
    sql = _extract_insert_sql()
    # 匹配 cleaned_winner_name = EXCLUDED.cleaned_winner_name 子句
    pattern = r'cleaned_winner_name\s*=\s*COALESCE\s*\(\s*NULLIF\s*\(\s*EXCLUDED\.cleaned_winner_name'
    assert re.search(pattern, sql, re.IGNORECASE), (
        f"cleaned_winner_name 没保护 (空值会覆盖手工填值)!\n--- SQL ---\n{sql}"
    )


def test_values_tuple_includes_cleaned_winner_name():
    """values.append tuple 必须含 cleaned_winner_name (位置 7), 跟 SQL 列对齐."""
    import ast
    from app.database import db as db_module
    src = inspect.getsource(db_module.Database.upsert_bid_results)
    # 找 values.append((...)) 块 (跨多行, 用 DOTALL, 非贪婪)
    m = re.search(r'values\.append\((\(.+?\))\)', src, re.DOTALL)
    assert m, "未找到 values.append tuple"
    # AST 解析 tuple
    try:
        tree = ast.parse(m.group(1), mode='eval')
    except SyntaxError as e:
        # 含注释 → 先 strip
        cleaned = re.sub(r'#[^\n]*', '', m.group(1))
        tree = ast.parse(cleaned, mode='eval')
    tuple_node = tree.body
    assert isinstance(tuple_node, ast.Tuple), f"不是 tuple: {type(tuple_node)}"
    assert len(tuple_node.elts) == 13, (
        f"values tuple 字段数不对 (期望 13): {len(tuple_node.elts)}\n"
        f"fields: {[ast.unparse(e) for e in tuple_node.elts]}"
    )
    fields_src = [ast.unparse(e) for e in tuple_node.elts]
    assert any('cleaned_winner_name' in f for f in fields_src), (
        f"values tuple 缺 cleaned_winner_name:\n{fields_src}"
    )


def test_dedup_key_uses_cleaned_winner_name():
    """seen key (去重) 必须用 cleaned_winner_name, 跟 DB 唯一约束对齐."""
    from app.database import db as db_module
    src = inspect.getsource(db_module.Database.upsert_bid_results)
    # dedup key tuple 应该有 4 个元素, 最后一个用 cleaned_winner_name
    assert 'dedup_key' in src, "未找到 dedup_key 局部变量"
    # 确保 dedup_key 优先用 cleaned_winner_name
    assert "r.get('cleaned_winner_name')" in src, (
        "dedup_key 没从 row dict 取 cleaned_winner_name"
    )
