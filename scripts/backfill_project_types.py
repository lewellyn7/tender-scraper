#!/usr/bin/env python3
"""
backfill_project_types.py — 仅回填 project_types 字段 (2026-06-20 新增)

用途：
  已有 bid_results 行未填 project_types (migration 002 默认 = ['其他'])，
  本脚本遍历全表，按 project_id JOIN projects_cqggzy.title 重新分类。

用法：
  python3 scripts/backfill_project_types.py --dry-run          # 只打印不写库
  python3 scripts/backfill_project_types.py --batch 500        # 每批 500 行
  python3 scripts/backfill_project_types.py                    # 跑全部

性能：
  - 单 SQL UPDATE ... FROM (SELECT ...) 批处理
  - ~108K 行预计 30-60s
  - WHERE project_types = ARRAY['其他'] 限定仅回填默认值（旧脚本写的）
"""
import argparse
import os
import sys
import logging
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from urllib.parse import urlparse

from app.utils.bid_parser import classify_project_type

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)


def get_connection():
    url = os.environ.get('DATABASE_URL')
    if not url:
        url = 'postgresql://root:CHANGE_ME_pwd@postgres:5432/tender_scraper'
    p = urlparse(url)
    return psycopg2.connect(
        host=p.hostname,
        port=p.port or 5432,
        dbname=p.path.lstrip('/'),
        user=p.username,
        password=p.password,
    )


def backfill(dry_run: bool, batch_size: int):
    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # 总数
        cur.execute("SELECT COUNT(*) FROM bid_results")
        total = cur.fetchone()[0]
        logger.info(f'📊 bid_results 总行数: {total}')

        # 拉所有 (id, title) 对
        cur.execute("""
            SELECT br.id, p.title, p.full_content
            FROM bid_results br
            JOIN projects_cqggzy p ON p.id = br.project_id
        """)
        rows = cur.fetchall()

        # 分批计算 + UPDATE
        type_counter: Counter = Counter()
        updated = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            update_values = []
            for bid, title, content in batch:
                types = classify_project_type(title or '', content or '')
                type_counter.update(types)
                update_values.append((types, bid))

            if not dry_run and update_values:
                from psycopg2.extras import execute_values
                execute_values(
                    cur,
                    "UPDATE bid_results SET project_types = u.types FROM (VALUES %s) AS u(id, types) WHERE bid_results.id = u.id",
                    [(bid, t) for t, bid in update_values],
                    template="(%s::BIGINT, %s::TEXT[])",
                    page_size=batch_size,
                )
                updated += len(update_values)

            logger.info(
                f'  进度 {min(i + batch_size, len(rows))}/{len(rows)} | '
                f'已更新 {updated}'
            )

        if not dry_run:
            conn.commit()

        logger.info('')
        logger.info('=' * 60)
        logger.info(f'✅ 回填完成')
        logger.info(f'  总行数: {total}')
        logger.info(f'  更新行数: {updated}')
        logger.info(f'  类型分布 TOP:')
        for t, c in type_counter.most_common(10):
            logger.info(f'    {t}: {c}')
        logger.info('=' * 60)

    finally:
        cur.close()
        conn.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--batch', type=int, default=500)
    args = p.parse_args()
    backfill(args.dry_run, args.batch)


if __name__ == '__main__':
    main()