#!/usr/bin/env python3
"""
Backfill 脚本: 回填 content_preview (2026-06-29)

场景: 列表 API 不返回 content (AGENTS.md 6-3 教训), 详情阶段 make_content_preview
      对答疑补遗等附件类内容清洗后返回空 → 17 条 cqggzy 行 content_preview 为空.

修法: 重新跑 make_content_preview (含 2026-06-29 兜底逻辑) + 写回 DB.
     对 full_content 也为空的行 (如 fahcqmu 7 条), 跳过 (需 detail 重采).

使用:
  python3 scripts/backfill_empty_content_preview_2026_06_29.py [--dry-run]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from app.database.db import get_db
from app.utils.clean_noise import make_content_preview


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计不写")
    parser.add_argument("--limit", type=int, default=10000, help="最大回填数")
    args = parser.parse_args()

    db = get_db()
    # 检测 DB 类型: psycopg2 连接 用 %s, sqlite 用 ?
    # 看 startup log "DB (singleton): ... PG=True" 提取
    # 先调 _get_conn() 触发 init log
    db._get_conn()
    # 再检测 - 看连接对象类型 (psycopg2 connection 有 'cursor()' 返回 pg cursor)
    test_conn = db._get_conn()
    db_name = "postgres" if test_conn.__class__.__name__ == "PGConnectionWrapper" else "sqlite"
    logger.info(f"DB backend: {db_name}, conn type: {test_conn.__class__.__module__}")

    conn = db._get_conn()
    cur = conn.cursor()

    tables = ("projects_cqggzy", "projects_ccgp", "projects_fahcqmu")
    total_updated = 0
    total_skipped = 0
    summary = []

    for tbl in tables:
        logger.info(f"\n=== {tbl} ===")
        # 查空 cp 且 fc 非空 的行
        if db_name == "postgres":
            cur.execute(
                f"SELECT url, full_content, title FROM {tbl} "
                f"WHERE (content_preview IS NULL OR content_preview = '') "
                f"AND full_content IS NOT NULL AND full_content != '' "
                f"LIMIT {args.limit}"
            )
        else:
            cur.execute(
                f"SELECT url, full_content, title FROM {tbl} "
                f"WHERE (content_preview IS NULL OR content_preview = '') "
                f"AND full_content IS NOT NULL AND full_content != '' "
                f"LIMIT {args.limit}"
            )
        rows = cur.fetchall()
        logger.info(f"找到 {len(rows)} 行需要回填")

        updated = 0
        skipped = 0
        for row in rows:
            url, fc, title = row[0], row[1], row[2]
            new_cp = make_content_preview(fc, title or "")
            if not new_cp:
                skipped += 1
                continue
            if not args.dry_run:
                if db_name == "postgres":
                    cur.execute(
                        f"UPDATE {tbl} SET content_preview = %s WHERE url = %s",
                        (new_cp, url),
                    )
                else:
                    cur.execute(
                        f"UPDATE {tbl} SET content_preview = ? WHERE url = ?",
                        (new_cp, url),
                    )
            updated += 1
            if updated <= 3:
                logger.info(f"  sample url={url[:60]}...")
                logger.info(f"         cp={new_cp[:120]}")

        if not args.dry_run:
            if db_name == "postgres":
                conn.commit()
            else:
                conn.commit()
        total_updated += updated
        total_skipped += skipped
        summary.append((tbl, len(rows), updated, skipped))

    logger.info("\n=== 汇总 ===")
    for tbl, found, upd, skp in summary:
        logger.info(f"{tbl}: 找到 {found}, 回填 {upd}, 跳过 {skp}")
    logger.info(f"总计: 回填 {total_updated}, 跳过 {total_skipped}, dry_run={args.dry_run}")
    cur.close()


if __name__ == "__main__":
    main()