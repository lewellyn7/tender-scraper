#!/usr/bin/env python3
"""
一次性回填 content_preview：用 make_content_preview 重新生成
- 仅 UPDATE content_preview 字段，不动 full_content / scraped_at / updated_at
- 仅当 new_preview != old_preview 时才更新（精准更新）
- 调用：docker exec -i tender-scraper-collector python3 /app/scripts/cleanup_content_preview.py [--dry-run]
"""
import sys
sys.path.insert(0, '/app')

from app.utils.clean_noise import make_content_preview
from app.database.db import _pg_conn
from psycopg2.extras import execute_batch

DRY_RUN = '--dry-run' in sys.argv


def main():
    print(f"=== content_preview 回填 (DRY_RUN={DRY_RUN}) ===\n", flush=True)

    conn = _pg_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, title, full_content, content_preview
        FROM projects_cqggzy
        ORDER BY id
    """)
    rows = cur.fetchall()
    print(f"全表: {len(rows)} 行\n", flush=True)

    updates = []
    skipped = 0
    for row_id, title, full_content, old_preview in rows:
        new_preview = make_content_preview(full_content or '', title or '', max_len=500)
        old = old_preview if old_preview is not None else ''
        new = new_preview if new_preview is not None else ''
        if new == old:
            skipped += 1
            continue
        updates.append((new_preview, row_id))

    print(f"需要更新: {len(updates)} 行 (跳过无变化: {skipped} 行)\n", flush=True)

    if not updates:
        print("无更新，退出", flush=True)
        return

    # 采样 5 条
    print("--- 采样前 5 条变更 ---", flush=True)
    for i, (new_preview, row_id) in enumerate(updates[:5]):
        cur.execute("SELECT title, content_preview FROM projects_cqggzy WHERE id = %s", (row_id,))
        title, old = cur.fetchone()
        old = old or ''
        new = new_preview or ''
        print(f"\n[#{i+1}] id={row_id} title={title[:40]}", flush=True)
        print(f"  OLD ({len(old)}字): {old[:120]}{'...' if len(old) > 120 else ''}", flush=True)
        print(f"  NEW ({len(new)}字): {new[:120]}{'...' if len(new) > 120 else ''}", flush=True)
    print("\n" + "=" * 60, flush=True)

    if DRY_RUN:
        print("DRY_RUN 模式，未执行 UPDATE", flush=True)
        return

    sql = "UPDATE projects_cqggzy SET content_preview = %s WHERE id = %s"
    execute_batch(cur, sql, updates, page_size=500)
    conn.commit()
    print(f"\n✅ UPDATE 完成: {len(updates)} 行", flush=True)

    cur.execute("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE content_preview IS NOT NULL AND content_preview != '') AS filled,
            COUNT(*) FILTER (WHERE content_preview LIKE '%重庆市公共资源交易网%') AS chrome_残留,
            COUNT(*) FILTER (WHERE content_preview = LEFT(title, 100)) AS title_重复
        FROM projects_cqggzy
    """)
    total, filled, chrome, title_dup = cur.fetchone()
    print(f"\n--- 跑后统计 ---", flush=True)
    print(f"总行数:      {total}", flush=True)
    print(f"preview 填充: {filled} ({filled*100.0/total:.1f}%)", flush=True)
    print(f"chrome 残留:  {chrome} (跑前 1433)", flush=True)
    print(f"title 重复:   {title_dup} (跑前 626)", flush=True)

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
