#!/usr/bin/env python3
"""
修复 Type B 跨分类脏数据: path /014001/ + cat=014005xxx
策略:
  - 12 条: 新 URL 不存在 → UPDATE url
  - 11 条: 新 URL 已存在 (新采的) → DELETE 旧记录
"""
import os
import sys
import psycopg2
import re

DRY_RUN = '--execute' not in sys.argv


def main():
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()

    cur.execute("""
        SELECT id, url, title
        FROM projects_cqggzy
        WHERE url LIKE '%/trade/014001/%'
          AND url LIKE '%categoryNum=014005%'
        ORDER BY id
    """)
    rows = cur.fetchall()
    print(f'[DRY_RUN={DRY_RUN}] Type B 总数: {len(rows)}')

    to_update = []  # (id, new_url, title)
    to_delete = []  # (id, old_url, title)
    for row_id, old_url, title in rows:
        new_url = old_url.replace('/trade/014001/', '/trade/014005/')
        cur.execute('SELECT id FROM projects_cqggzy WHERE url = %s', (new_url,))
        if cur.fetchone():
            to_delete.append((row_id, old_url, title))
        else:
            to_update.append((row_id, new_url, title))

    print(f'  UPDATE (新 URL 不存在): {len(to_update)}')
    print(f'  DELETE (新 URL 已存在): {len(to_delete)}')

    if DRY_RUN:
        print('\n[DRY] === 预览 UPDATE ===')
        for row_id, new_url, title in to_update[:5]:
            print(f'  id={row_id} → {new_url[-60:]} | {title[:35]}')
        if len(to_update) > 5:
            print(f'  ... 还有 {len(to_update) - 5} 条')
        print('\n[DRY] === 预览 DELETE ===')
        for row_id, old_url, title in to_delete[:5]:
            print(f'  id={row_id} {old_url[-50:]} | {title[:35]}')
        if len(to_delete) > 5:
            print(f'  ... 还有 {len(to_delete) - 5} 条')
        print('\nℹ️  Dry run, 加 --execute 真正执行')
        return 0

    # 真正执行
    for row_id, new_url, _ in to_update:
        cur.execute('UPDATE projects_cqggzy SET url = %s WHERE id = %s', (new_url, row_id))
    for row_id, _, _ in to_delete:
        cur.execute('DELETE FROM projects_cqggzy WHERE id = %s', (row_id,))
    conn.commit()
    print(f'\n✓ UPDATE {len(to_update)}, DELETE {len(to_delete)}, 总操作 {len(to_update) + len(to_delete)}')

    # 验证
    cur.execute("SELECT COUNT(*) FROM projects_cqggzy WHERE url LIKE '%/trade/014001/%' AND url LIKE '%categoryNum=014005%'")
    print(f'✓ 残留 Type B: {cur.fetchone()[0]}')

    cur.close()
    conn.close()


if __name__ == '__main__':
    sys.exit(main())
