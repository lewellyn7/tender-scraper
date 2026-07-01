#!/usr/bin/env python3
"""回填 bid_results.cleaned_winner_name 用新版 clean_winner_name.

7-01 拓展:
  - 覆盖工程招投标中标候选人公示中常见的 10+ 未清洗模式
  - HTML 实体清理
  - 多 pass 清洗
  - 中文标点支持

铁律 (AGENTS.md):
  - SELECT 验证匹配数 (Step 1)
  - LIMIT 起步 (默认全量, --limit N 限制)
  - 演练 dry-run → 真跑
  - 备份已完成 (.pre-qual-feature/bid-winner-clean-v2-2026-07-01/bid_results_backup_20260701_1600.sql)

执行:
  python3 scripts/backfill_clean_winner_v2.py --dry-run            # 干跑, 看会改多少
  python3 scripts/backfill_clean_winner_v2.py --dry-run --limit 50  # 抽样 50 行
  python3 scripts/backfill_clean_winner_v2.py --limit 10            # 真实改 10 行 (测试)
  python3 scripts/backfill_clean_winner_v2.py                       # 真实改全量
"""
import sys
import os
import re
import argparse
import logging
from pathlib import Path

# 加 project root 到 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.utils.bid_parser import clean_winner_name
from app.database.db import get_db, USE_PG

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('backfill_clean_winner_v2')


def get_conn(db):
    """Get PG connection (用 _local.pg_conn)."""
    if not hasattr(db._local, 'pg_conn') or db._local.pg_conn is None:
        db._local.pg_conn = db._get_conn().conn
    return db._local.pg_conn


def analyze(dry_run: bool = True, limit: int = None):
    """分析 + 回填 cleaned_winner_name."""
    db = get_db()
    log.info(f"DB type: {'PG' if USE_PG else 'SQLite'}")

    placeholder = '%s' if USE_PG else '?'

    # Step 1: SELECT 验证总数
    conn = get_conn(db)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM bid_results")
    total = cur.fetchone()[0]
    log.info(f"Total bid_results rows: {total}")

    # Step 2: 查询需要重清洗的行
    # 7-01 v2: 扩展条件覆盖早期 max_len=30 留下的伪清洗行 (eg '资质：建筑工程...')
    cur.execute("""
        SELECT id, source, project_id, package_no, winner_name, cleaned_winner_name
        FROM bid_results
        WHERE winner_name IS NOT NULL
          AND (
            cleaned_winner_name IS NULL
            OR cleaned_winner_name = ''
            OR length(cleaned_winner_name) > 30
            OR cleaned_winner_name ~ '资质|业绩|候选人|联合体|否决|比选|详见|资格'
            OR cleaned_winner_name ~ '^无[。,，;；：:\\s]'
            OR cleaned_winner_name ~ '^[/\\-\\—]'
            OR cleaned_winner_name = winner_name  -- 早期未清洗
          )
        ORDER BY id
    """)
    rows = cur.fetchall()
    log.info(f"Will consider: {len(rows)} rows")

    if limit:
        rows = rows[:limit]
        log.info(f"Limited to first {limit} rows")

    # Step 3: 模拟新清洗
    stats = {'changed': 0, 'same': 0, 'to_null': 0, 'unchanged': 0, 'protected': 0}
    samples = []
    for row in rows:
        rowid, source, pid, pno, raw_winner, old_cleaned = row
        if not raw_winner:
            continue
        new_cleaned = clean_winner_name(raw_winner)
        if new_cleaned != (old_cleaned or ''):
            stats['changed'] += 1
            if new_cleaned is None:
                stats['to_null'] += 1
            if len(samples) < 8:
                samples.append({
                    'id': rowid,
                    'old': old_cleaned,
                    'new': new_cleaned,
                    'raw': raw_winner[:100]
                })
        else:
            stats['unchanged'] += 1

    log.info(f"Stats: {stats}")
    if samples:
        log.info("Sample changes (前 8):")
        for s in samples:
            log.info(f"  id={s['id']}: old={s['old']!r} → new={s['new']!r}")
            log.info(f"    raw: {s['raw']!r}")

    if dry_run:
        log.info("DRY-RUN: 不写入, 如确认执行去掉 --dry-run")
        return

    # Step 4: 真跑 (逐行 UPDATE)
    log.info("Starting UPDATE...")
    updated = 0
    protected = 0
    for row in rows:
        rowid, source, pid, pno, raw_winner, old_cleaned = row
        if not raw_winner:
            continue
        new_cleaned = clean_winner_name(raw_winner)
        if new_cleaned != (old_cleaned or ''):
            # 保护: 旧值非空且看起来像合法公司名 (不含脏字) → 跳过 (避免空值覆盖)
            # 7-01 v2: 旧值含脏字 (eg '资质:xxx' 早期 max_len=30 留下的伪清洗) → 不保护, 强制更新
            if old_cleaned and not new_cleaned:
                if not re.search(r'资质|业绩|候选人|联合体|否决|比选|详见|资格|^无|^[/.]', old_cleaned):
                    protected += 1
                    continue
            cur.execute(
                f"UPDATE bid_results SET cleaned_winner_name = {placeholder} WHERE id = {placeholder}",
                (new_cleaned, rowid)
            )
            updated += 1
    conn.commit()
    log.info(f"Updated: {updated} rows, Protected (skipped): {protected}")


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--dry-run', action='store_true', help='只分析, 不写库')
    p.add_argument('--limit', type=int, default=None, help='只处理前 N 行 (测试用)')
    args = p.parse_args()
    analyze(dry_run=args.dry_run, limit=args.limit)
