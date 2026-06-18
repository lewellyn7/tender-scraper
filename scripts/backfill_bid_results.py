#!/usr/bin/env python3
"""
backfill_bid_results.py — 中标结果历史回填

用法:
  python3 scripts/backfill_bid_results.py --dry-run          # 只打印不写库
  python3 scripts/backfill_bid_results.py --after 2026-01-01 # 从某日期起
  python3 scripts/backfill_bid_results.py --limit 100         # 限制条数
  python3 scripts/backfill_bid_results.py                    # 跑全部

行为:
- 读 projects_cqggzy 中 info_type IN (采购结果公告, 中标候选人公示, 中标结果公示)
- 对每条 full_content 调 app.utils.bid_parser.parse_bid_results
- 解析失败的条 → 写日志 (WARN), 跳过, 不阻塞
- 解析成功 → 批量 UPSERT 到 bid_results 表
- 废标公告 → 跳过, 不入表 (用户决策 2026-06-18)
- 进度: 每 100 条打印一次
"""
import argparse
import os
import sys
import logging
from datetime import date
from decimal import Decimal

# 项目根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from psycopg2.extras import execute_values
from psycopg2 import sql

from app.utils.bid_parser import parse_bid_results

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# ─── DB Connection ────────────────────────────────────────────────────────────

def get_connection():
    """从 DATABASE_URL env 解析 (本地/CI 用 localhost, 容器用 docker 网络)."""
    url = os.environ.get('DATABASE_URL')
    if not url:
        # 容器内 fallback
        url = 'postgresql://root:***@postgres:5432/tender_scraper'
    from urllib.parse import urlparse
    p = urlparse(url)
    return psycopg2.connect(
        host=p.hostname,
        port=p.port or 5432,
        dbname=p.path.lstrip('/'),
        user=p.username,
        password=p.password,
    )


# ─── 核心 ETL ────────────────────────────────────────────────────────────────

def fetch_target_records(cur, after_date: str, limit: int | None) -> list:
    """取需要解析的源记录."""
    sql_q = """
        SELECT id, url, info_type, category, full_content, publish_date
        FROM projects_cqggzy
        WHERE info_type IN ('采购结果公告', '中标候选人公示', '中标结果公示')
          AND publish_date >= %s
          AND full_content IS NOT NULL
          AND LENGTH(full_content) > 100
        ORDER BY id
    """
    if limit:
        sql_q += f" LIMIT {int(limit)}"
    cur.execute(sql_q, (after_date,))
    return cur.fetchall()


def upsert_bid_rows(cur, rows: list) -> int:
    """批量 UPSERT 到 bid_results. 返回写入条数."""
    if not rows:
        return 0
    # 按 UNIQUE 字段去重 (同 batch 里两条 winner_name+package_no 相同会触发 DO UPDATE 冲突)
    seen = set()
    values = []
    for r in rows:
        key = (
            r.get('source', 'cqggzy'),
            r['project_id'],
            r['package_no'],
            r['winner_name'],
        )
        if key in seen:
            continue
        seen.add(key)
        values.append((
            r.get('source', 'cqggzy'),
            r['project_id'],
            r['url'],
            r['info_type'],
            r['category'],
            r['package_no'],
            r['winner_name'],
            r['winner_rank'],
            r['bid_amount'],
            r['bid_amount_num'],
            r['winner_score'],
            r['publish_date'],
        ))
    if not values:
        return 0
    sql_q = """
        INSERT INTO bid_results (
          source, project_id, url, info_type, category, package_no,
          winner_name, winner_rank, bid_amount, bid_amount_num,
          winner_score, publish_date
        )
        VALUES %s
        ON CONFLICT (source, project_id, package_no, winner_name)
        DO UPDATE SET
          info_type = EXCLUDED.info_type,
          category = EXCLUDED.category,
          winner_rank = EXCLUDED.winner_rank,
          bid_amount = EXCLUDED.bid_amount,
          bid_amount_num = EXCLUDED.bid_amount_num,
          winner_score = EXCLUDED.winner_score,
          publish_date = EXCLUDED.publish_date,
          parsed_at = NOW()
    """
    execute_values(cur, sql_q, values, page_size=200)
    return len(values)


# ─── 主流程 ──────────────────────────────────────────────────────────────────

def backfill(after_date: str, limit: int | None, dry_run: bool):
    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        records = fetch_target_records(cur, after_date, limit)
        logger.info(f'📥 源记录 {len(records)} 条 (after={after_date})')

        if dry_run:
            logger.info('🔍 DRY-RUN 模式 — 不写库')

        total_parsed = 0
        total_upserted = 0
        parse_failures = 0
        upsert_failures = 0
        aborted_count = 0
        empty_count = 0

        for i, (proj_id, url, info_type, category, full_content, pub_date) in enumerate(records, 1):
            try:
                rows = parse_bid_results(
                    content=full_content,
                    info_type=info_type,
                    category=category,
                    project_id=proj_id,
                    url=url,
                    publish_date=pub_date,
                )

                if not rows:
                    from app.utils.bid_parser import is_aborted
                    if is_aborted(full_content):
                        aborted_count += 1
                    else:
                        empty_count += 1
                    continue

                total_parsed += len(rows)

                if dry_run:
                    if i <= 3:
                        logger.info(f'  [示例] id={proj_id} {info_type}: {len(rows)} 行')
                        for r in rows[:2]:
                            logger.info(f'    {r["winner_name"]} (¥{r["bid_amount_num"] or "?"})')
                else:
                    # 每条独立 savepoint, 失败不影响后续
                    try:
                        cur.execute('SAVEPOINT sp_upsert')
                        upserted = upsert_bid_rows(cur, rows)
                        total_upserted += upserted
                        cur.execute('RELEASE SAVEPOINT sp_upsert')
                    except Exception as e:
                        cur.execute('ROLLBACK TO SAVEPOINT sp_upsert')
                        upsert_failures += 1
                        if upsert_failures <= 5:
                            logger.warning(f'⚠️ id={proj_id} upsert 失败: {e}')
                            for r in rows[:1]:
                                logger.warning(f'   winner={r["winner_name"]!r} amount={r["bid_amount_num"]} date={r["publish_date"]}')

                    if i % 100 == 0:
                        conn.commit()
                        logger.info(
                            f'  进度 {i}/{len(records)} | '
                            f'已解析 {total_parsed} 行, 已写入 {total_upserted} 行, '
                            f'废标 {aborted_count}, 无winner {empty_count}, '
                            f'upsert 失败 {upsert_failures}'
                        )

            except Exception as e:
                parse_failures += 1
                logger.warning(f'⚠️ id={proj_id} 解析失败: {e}')
                continue

        if not dry_run:
            conn.commit()

        # 汇总
        logger.info('')
        logger.info('=' * 60)
        logger.info(f'✅ 回填完成')
        logger.info(f'  源记录: {len(records)}')
        logger.info(f'  解析行数: {total_parsed}')
        if not dry_run:
            logger.info(f'  写入行数: {total_upserted}')
            logger.info(f'  upsert 失败: {upsert_failures}')
        logger.info(f'  废标跳过: {aborted_count}')
        logger.info(f'  无winner: {empty_count}')
        logger.info(f'  解析失败: {parse_failures}')
        logger.info('=' * 60)

    finally:
        cur.close()
        conn.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--after', default='2026-01-01', help='起始日期 (YYYY-MM-DD)')
    p.add_argument('--limit', type=int, default=None, help='限制条数')
    p.add_argument('--dry-run', action='store_true', help='只解析不写库')
    args = p.parse_args()

    backfill(args.after, args.limit, args.dry_run)


if __name__ == '__main__':
    main()