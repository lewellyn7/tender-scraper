#!/usr/bin/env python3
"""从 PostgreSQL 读取所有记录，用 summarize 规则重新生成 project_overview

用法: python scripts/regenerate_overviews.py [--limit 100]
"""
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import loguru
logger = loguru.logger
logger.remove()
logger.add(sys.stderr, level="INFO")

import psycopg2
import psycopg2.extras
from app.utils.summarize import summarize

DB_URL = "postgresql://root:root123@localhost:5435/tender_scraper"


def get_connection():
    return psycopg2.connect(DB_URL)


def regenerate_all():
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # 读取所有有 info_type 的记录
    cur.execute("""
        SELECT id, title, info_type, business_type, full_content,
               budget, bid_amount, submission_deadline,
               contact_name, contact_phone, region
        FROM projects_cqggzy
        WHERE info_type IS NOT NULL AND info_type != ''
        ORDER BY id
    """)
    rows = cur.fetchall()
    total = len(rows)
    logger.info(f"📥 读取 {total} 条记录，开始重新生成 project_overview")

    updated = 0
    errors = 0
    stats = {}

    for row in rows:
        try:
            info_type = row['info_type'] or ''
            if not info_type:
                continue

            overview = summarize(
                info_type=info_type,
                title=row['title'] or '',
                budget=row.get('budget') or '',
                bid_amount=row.get('bid_amount') or '',
                submission_deadline=row.get('submission_deadline') or '',
                contact_name=row.get('contact_name') or '',
                contact_phone=row.get('contact_phone') or '',
                region=row.get('region') or '',
                full_content=row.get('full_content') or '',
            )

            cur.execute(
                "UPDATE projects_cqggzy SET project_overview = %s WHERE id = %s",
                (overview, row['id'])
            )
            updated += 1

            # 统计
            key = info_type
            stats[key] = stats.get(key, 0) + 1

            if updated % 50 == 0:
                logger.info(f"  进度: {updated}/{total}")

        except Exception as e:
            errors += 1
            logger.warning(f"⚠️ id={row['id']} error: {e}")

    conn.commit()
    cur.close()
    conn.close()

    logger.info(f"\n✅ 完成！更新 {updated} 条，失败 {errors} 条")
    logger.info("各类型分布:")
    for k, v in sorted(stats.items()):
        logger.info(f"  {k}: {v}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="限制条数(调试用)")
    args = parser.parse_args()

    if args.limit > 0:
        logger.info(f"⚠️ 限制模式: 仅处理 {args.limit} 条")

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, title, info_type, business_type, full_content, budget, bid_amount, submission_deadline, contact_name, contact_phone, region FROM projects_cqggzy WHERE info_type IS NOT NULL AND info_type != '' ORDER BY id" + (f" LIMIT {args.limit}" if args.limit else ""))
    rows = cur.fetchall()
    total = len(rows)
    logger.info(f"📥 读取 {total} 条")
    conn.close()

    if args.limit:
        rows = rows[:args.limit]

    conn2 = get_connection()
    cur2 = conn2.cursor()
    updated = 0
    stats = {}
    for row in rows:
        try:
            info_type = row['info_type'] or ''
            overview = summarize(
                info_type=info_type,
                title=row['title'] or '',
                budget=row.get('budget') or '',
                bid_amount=row.get('bid_amount') or '',
                submission_deadline=row.get('submission_deadline') or '',
                contact_name=row.get('contact_name') or '',
                contact_phone=row.get('contact_phone') or '',
                region=row.get('region') or '',
                full_content=row.get('full_content') or '',
            )
            cur2.execute("UPDATE projects_cqggzy SET project_overview = %s WHERE id = %s", (overview, row['id']))
            updated += 1
            key = info_type or 'empty'
            stats[key] = stats.get(key, 0) + 1
            if updated % 50 == 0:
                logger.info(f"  进度: {updated}/{total}")
        except Exception as e:
            logger.warning(f"⚠️ id={row['id']} {e}")
    conn2.commit()
    conn2.close()
    logger.info(f"✅ 更新 {updated} 条 | 分布: {stats}")