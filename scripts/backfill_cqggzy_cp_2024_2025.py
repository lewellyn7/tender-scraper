#!/usr/bin/env python3
"""
一次性 Backfill 脚本: 给 cqggzy 2024-2025 范围缺 content_preview 的 9,862 条
从已有 full_content 截取前 300 字生成 content_preview.

2026-06-26: PR feat/cqggzy-cp-backfill-2024-2025

为什么这个脚本:
- 6-5 上线 6 步后, list API 不返回 content, 但 detail 阶段也只填了部分 fc
- 9,862 条 (11% of 86,181) 有 fc 但缺 cp, 导致 Data 页"列表卡片"显示空白摘要
- 不重抓详情页 (B 方案: 慢, 反爬风险), 改用已有 fc 截 300 字

设计:
- 1 次 SQL: SELECT 需要 cp 的 url + full_content
- 1 次 SQL: 批量 UPDATE (使用 generate_series + CASE WHEN 太复杂, 用 executemany 分批)
- 保护: 只在 content_preview 为 NULL/'' 时更新, 不覆盖已有值
- 干跑模式: --dry-run, 不写 DB, 只统计

用法:
    # 干跑 (看统计)
    docker exec tender-scraper-web python3 /app/scripts/backfill_cqggzy_cp_2024_2025.py --dry-run
    
    # 实跑
    docker exec tender-scraper-web python3 /app/scripts/backfill_cqggzy_cp_2024_2025.py
"""

import argparse
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, "/app")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://root:root123@postgres:5432/tender_scraper",
)

import psycopg2
from psycopg2.extras import execute_values

# ━━━ 配置 ━━━
CP_MAX_LEN = 300  # content_preview 长度 (与 API 截取一致)
BATCH_SIZE = 500  # 每批 UPDATE 行数
TABLE = "projects_cqggzy"
DATE_START = "2024-01-01"
DATE_END = "2025-12-31"


def make_cp(full_content: str) -> str:
    """从 full_content 生成 content_preview.
    
    规则:
    - 取前 300 字
    - 移除换行
    - 移除多余空白
    - 优先在句末断句 (300 字内最后一个 . 。 / n 换行)
    """
    if not full_content:
        return ""
    # 移除换行 + 多余空白
    text = " ".join(full_content.split())
    if len(text) <= CP_MAX_LEN:
        return text
    # 截 300 字, 尝试在 . / 。 / ！ / ? 边界断
    truncated = text[:CP_MAX_LEN]
    for sep in ["。", ".", "!", "?", "!", "？", ";", "；", "\n"]:
        idx = truncated.rfind(sep)
        if idx > CP_MAX_LEN * 0.7:  # 至少 70% 内容保留
            return truncated[: idx + 1].strip()
    return truncated.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    parser.add_argument("--batch", type=int, default=BATCH_SIZE, help=f"批量大小 (默认 {BATCH_SIZE})")
    args = parser.parse_args()

    print(f"\n{'='*70}")
    print(f"  Backfill: {TABLE} {DATE_START} ~ {DATE_END} 缺 content_preview")
    print(f"  CP 长度: {CP_MAX_LEN} 字")
    print(f"  批量: {args.batch}")
    print(f"  模式: {'DRY-RUN (不写库)' if args.dry_run else 'WRITE (实跑)'}")
    print(f"{'='*70}\n")

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    # 1. 统计
    cur.execute(f"""
        SELECT COUNT(*)
        FROM {TABLE}
        WHERE publish_date BETWEEN %s AND %s
          AND (content_preview IS NULL OR content_preview = '')
          AND full_content IS NOT NULL AND full_content != ''
    """, (DATE_START, DATE_END))
    total = cur.fetchone()[0]
    print(f"  待补: {total} 条")

    if total == 0:
        print("\n  ✓ 无需补采")
        return

    # 2. 干跑: 取样 5 条
    cur.execute(f"""
        SELECT url, title, full_content
        FROM {TABLE}
        WHERE publish_date BETWEEN %s AND %s
          AND (content_preview IS NULL OR content_preview = '')
          AND full_content IS NOT NULL AND full_content != ''
        LIMIT 5
    """, (DATE_START, DATE_END))
    print(f"\n  干跑样例 (前 5 条):")
    for url, title, fc in cur.fetchall():
        cp = make_cp(fc)
        print(f"    URL: {url[:80]}")
        print(f"    title: {title[:60]}")
        print(f"    fc_len: {len(fc)} → cp_len: {len(cp)}")
        print(f"    cp_preview: {cp[:100]!r}...")
        print()

    if args.dry_run:
        print(f"\n  [DRY-RUN] 不写库, 退出")
        return

    # 3. 实跑: 分批 SELECT + UPDATE
    print(f"  开始 UPDATE (批量 {args.batch})...")
    start_time = time.time()
    updated_total = 0
    skip_total = 0
    offset = 0

    while True:
        cur.execute(f"""
            SELECT id, full_content
            FROM {TABLE}
            WHERE publish_date BETWEEN %s AND %s
              AND (content_preview IS NULL OR content_preview = '')
              AND full_content IS NOT NULL AND full_content != ''
            ORDER BY id
            LIMIT %s OFFSET %s
        """, (DATE_START, DATE_END, args.batch, offset))
        rows = cur.fetchall()
        if not rows:
            break

        # 生成 (id, new_cp) 列表
        updates = []
        for row_id, fc in rows:
            new_cp = make_cp(fc)
            if new_cp:
                updates.append((new_cp, row_id))
            else:
                skip_total += 1

        if updates:
            # 批量 UPDATE (execute_values 一次提交)
            execute_values(
                cur,
                f"UPDATE {TABLE} SET content_preview = data.cp FROM (VALUES %s) AS data(id, cp) WHERE {TABLE}.id = data.id::bigint",
                [(rid, cp) for cp, rid in updates],
                template="(%s::bigint, %s)",
            )
            conn.commit()
            updated_total += len(updates)

        elapsed = time.time() - start_time
        rate = updated_total / elapsed if elapsed > 0 else 0
        eta = (total - updated_total - skip_total) / rate if rate > 0 else 0
        print(f"  Progress: {updated_total + skip_total}/{total} "
              f"({updated_total + skip_total*100//total}%) "
              f"updated={updated_total} skip={skip_total} "
              f"rate={rate:.0f}/s ETA={eta:.0f}s")
        offset += args.batch

    elapsed = time.time() - start_time
    print(f"\n{'='*70}")
    print(f"  ✓ 完成: 更新 {updated_total} 条, 跳过 {skip_total} 条, 用时 {elapsed:.1f}s")
    print(f"{'='*70}\n")

    # 4. 验证
    cur.execute(f"""
        SELECT COUNT(*)
        FROM {TABLE}
        WHERE publish_date BETWEEN %s AND %s
          AND (content_preview IS NULL OR content_preview = '')
    """, (DATE_START, DATE_END))
    remaining = cur.fetchone()[0]
    print(f"  验证: 2024-2025 范围仍缺 cp 的: {remaining} 条 (期望: 0)\n")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
