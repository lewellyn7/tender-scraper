"""
fix_publish_date.py — 回填 publish_date (v2 处理重复版 v2)

背景 (2026-06-15):
  - app/crawlers/cqggzy.py:739 _extract_publish_date_from_content 旧版用 re.search
    全文第一个匹配 → 014005 政府采购公告通常以"于 2026年X月X日 14:00 前递交投标文件"
    开头 → 投标截止日期先匹配 → 错误把截止日期当公告日期
  - 影响: 612932 等记录 publish_date = 2026-07-01 (错, 实际 6-9)

策略 (v2):
  1. 从 DB 拉受影响的记录 (publish_date_raw IS NULL + full_content 有值)
  2. 限定 info_type 白名单: 采购公告 / 招标公告 / 答疑补遗
     (排除变更公告/中标结果/终止公告, 这些含"首次公告日期"引用会误改)
  3. 调 _extract_publish_date_from_content 重新提取
  4. 仅当新日期 ≤ created_at (确保不是未来日期) 且 ≠ 旧日期 时更新
  5. 备份表 _publish_date_backup 记录所有改动, 方便回滚

用法:
  python scripts/fix_publish_date.py --dry-run   # 仅打印计划
  python scripts/fix_publish_date.py             # 实际更新
"""
import argparse
import os
import sys
import psycopg2

# 加载 .env
from pathlib import Path
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ.setdefault(k, v)

DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'port': int(os.environ.get('DB_PORT', '5435')),
    'database': os.environ.get('DB_NAME', 'tender_scraper'),
    'user': os.environ.get('DB_USER', 'root'),
    'password': os.environ.get('DB_PASSWORD', ''),
}

# info_type 白名单: 只回填"原始公告"类型, 排除含"首次公告日期"引用的变更公告
INFO_TYPE_WHITELIST = ('采购公告', '招标公告', '答疑补遗')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--limit', type=int, default=None, help='只处理 N 条 (测试)')
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from app.crawlers.cqggzy import _extract_publish_date_from_content

    print(f"\n{'='*60}")
    print(f"修复 publish_date 错位 ({'DRY-RUN' if args.dry_run else '实际更新'})")
    print(f"  限定 info_type: {INFO_TYPE_WHITELIST}")
    print(f"{'='*60}\n")

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # 1. 建备份表
    cur.execute('''
        CREATE TABLE IF NOT EXISTS _publish_date_backup (
            id INT PRIMARY KEY,
            old_publish_date DATE,
            new_publish_date DATE,
            title TEXT,
            fixed_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    conn.commit()

    # 2. 拉受影响记录
    placeholders = ','.join(['%s'] * len(INFO_TYPE_WHITELIST))
    sql = f'''
        SELECT id, title, publish_date, full_content, created_at
        FROM projects_cqggzy
        WHERE publish_date_raw IS NULL
          AND full_content IS NOT NULL AND full_content != ''
          AND info_type IN ({placeholders})
        ORDER BY id
    '''
    if args.limit:
        sql += f' LIMIT {args.limit}'
    cur.execute(sql, INFO_TYPE_WHITELIST)
    records = cur.fetchall()
    print(f'→ 待处理: {len(records)} 条\n')

    stats = {'updated': 0, 'unchanged': 0, 'would_future': 0, 'no_extract': 0, 'skipped': 0}
    samples = []

    for rid, title, old_pd, content, created_at in records:
        new_pd = _extract_publish_date_from_content(content or '')
        if new_pd is None:
            stats['no_extract'] += 1
            continue
        if new_pd == old_pd:
            stats['unchanged'] += 1
            continue
        if new_pd > created_at.date():
            stats['would_future'] += 1
            continue

        # 需要更新
        if not args.dry_run:
            try:
                cur.execute(
                    'INSERT INTO _publish_date_backup (id, old_publish_date, new_publish_date, title) VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET old_publish_date = EXCLUDED.old_publish_date, new_publish_date = EXCLUDED.new_publish_date, fixed_at = NOW()',
                    (rid, old_pd, new_pd, title[:200])
                )
                cur.execute('UPDATE projects_cqggzy SET publish_date = %s WHERE id = %s', (new_pd, rid))
                stats['updated'] += 1
            except Exception as e:
                conn.rollback()
                print(f'  ❌ [{rid}] {e}')
                stats['skipped'] += 1
                continue
        else:
            stats['updated'] += 1

        if len(samples) < 5:
            samples.append((rid, str(old_pd), str(new_pd), title[:50]))

    if not args.dry_run:
        conn.commit()
    else:
        conn.rollback()
    conn.close()

    print(f'\n=== 汇总 ===')
    print(f'  ✅ 更新: {stats["updated"]}')
    print(f'  — 未变: {stats["unchanged"]}')
    print(f'  ⚠️ 新日期>created_at (跳过): {stats["would_future"]}')
    print(f'  ⚠️ 无法提取: {stats["no_extract"]}')
    print(f'  ❌ 失败: {stats["skipped"]}')

    if samples:
        print(f'\n=== 变更样本 (前 5 条) ===')
        for rid, old, new, title in samples:
            print(f'  [{rid}] {old} → {new}: {title}')

    if args.dry_run:
        print(f'\n⚠️ DRY-RUN: 未写 DB, 重跑不带 --dry-run 执行')
    else:
        print(f'\n✅ 已 COMMIT. 备份表 _publish_date_backup 含所有改动.')


if __name__ == '__main__':
    main()
