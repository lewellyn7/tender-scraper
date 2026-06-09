#!/usr/bin/env python3
"""
一次性：用新 clean_text 重新计算全表 full_content
- 仅当 new_full_content != old_full_content 才 UPDATE
- 调用：docker exec -i tender-scraper-collector python3 /app/scripts/refresh_full_content.py [--dry-run]
"""
import sys
sys.path.insert(0, '/app')

from app.utils.clean_noise import clean_text
from app.database.db import _pg_conn
from psycopg2.extras import execute_batch

DRY_RUN = '--dry-run' in sys.argv
BATCH = 500


def main():
    print(f"=== full_content 全表刷新 (DRY_RUN={DRY_RUN}) ===\n", flush=True)

    conn = _pg_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, full_content FROM projects_cqggzy ORDER BY id")
    rows = cur.fetchall()

    updates = []
    skipped = 0
    for row_id, old_full in rows:
        old = old_full if old_full is not None else ''
        new = clean_text(old)
        if new == old:
            skipped += 1
            continue
        updates.append((new, row_id))

    print(f"全表: {len(rows)} 行", flush=True)
    print(f"需要更新: {len(updates)} 行 (跳过无变化: {skipped} 行)\n", flush=True)

    if not updates:
        print("无更新，退出", flush=True)
        return

    # 采样 3 条变更
    print("--- 采样前 3 条变更 ---", flush=True)
    for i, (new_content, row_id) in enumerate(updates[:3]):
        cur.execute("SELECT title, LEFT(full_content, 100) FROM projects_cqggzy WHERE id = %s", (row_id,))
        title, old_head = cur.fetchone()
        old_head = old_head or ''
        new_head = (new_content or '')[:100]
        print(f"\n[#{i+1}] id={row_id} title={title[:30]}", flush=True)
        print(f"  OLD: {old_head!r}", flush=True)
        print(f"  NEW: {new_head!r}", flush=True)

    # 估算新 chrome 残留
    cur.execute("SELECT COUNT(*) FROM projects_cqggzy")
    total = cur.fetchone()[0]
    new_chrome = sum(1 for (c, _) in updates if '重庆市公共资源交易网' in (c or '') or '您当前的位置' in (c or '') or '字号' in (c or '') or '保函' in (c or ''))
    print(f"\n--- 变更行内新 chrome 残留预测 ---", flush=True)
    print(f"新含 chrome 关键词: {new_chrome}/{len(updates)} (变更行内)", flush=True)
    print(f"全表 chrome 残留预测: ~{new_chrome} 行 (变更后估)", flush=True)

    print("\n" + "=" * 60, flush=True)

    if DRY_RUN:
        print("DRY_RUN 模式，未执行 UPDATE", flush=True)
        return

    sql = "UPDATE projects_cqggzy SET full_content = %s WHERE id = %s"
    execute_batch(cur, sql, updates, page_size=BATCH)
    conn.commit()
    print(f"\n✅ UPDATE 完成: {len(updates)} 行", flush=True)

    # 跑后统计
    cur.execute("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE full_content LIKE '%%重庆市公共资源交易网%%') AS plat,
            COUNT(*) FILTER (WHERE full_content LIKE '%%您当前的位置%%') AS pos,
            COUNT(*) FILTER (WHERE full_content LIKE '%%字号 大 中 小%%') AS size_c,
            COUNT(*) FILTER (WHERE full_content LIKE '%%申请投标保函%%') AS bond
        FROM projects_cqggzy
    """)
    total, plat, pos, size_c, bond = cur.fetchone()
    print(f"\n--- 跑后统计 (全表 {total} 行) ---", flush=True)
    print(f"平台 header:    {plat} (跑前估 4182)", flush=True)
    print(f"位置面包屑:     {pos}", flush=True)
    print(f"字号控件:       {size_c}", flush=True)
    print(f"投标保函:       {bond}", flush=True)

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
