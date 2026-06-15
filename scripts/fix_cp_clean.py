"""
fix_cp_clean.py — 回填 content_preview (2026-06-15)

背景:
  用户报告 "部分项目的内容摘要未清洗干净" (4 种异常).
  调研结论: 异常 2 (4126 条【】) + 异常 3 子集 (809 条页脚) 是 cp 清洗漏处理.
  修 clean_noise.py 后, 重跑这些记录的 cp 即可.

策略:
  1. 限定范围: full_content 有值 + content_preview 有值 (排除 1 万条 cp 空 = fc 空)
  2. 调 clean_noise + make_content_preview 重算
  3. 仅当新 cp ≠ 旧 cp 时更新
  4. 备份表 _cp_clean_backup 记录所有改动, 可回滚
  5. 保护 title (保留 title != 新 cp 约束, 避免 cp = title)

用法:
  python scripts/fix_cp_clean.py --dry-run
  python scripts/fix_cp_clean.py
"""
import argparse
import os
import sys
from pathlib import Path
import psycopg2

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--limit', type=int, default=None, help='只处理 N 条 (测试)')
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from app.utils.clean_noise import make_content_preview

    print(f"\n{'='*60}")
    print(f"重算 content_preview ({'DRY-RUN' if args.dry_run else '实际更新'})")
    print(f"{'='*60}\n")

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # 1. 建备份表
    cur.execute('''
        CREATE TABLE IF NOT EXISTS _cp_clean_backup (
            id INT PRIMARY KEY,
            old_content_preview TEXT,
            new_content_preview TEXT,
            title TEXT,
            fixed_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    conn.commit()

    # 2. 拉所有 fc + cp 有值的记录 (限制范围 = 必能产生有意义的新 cp)
    sql = '''
        SELECT id, title, content_preview, full_content
        FROM projects_cqggzy
        WHERE full_content IS NOT NULL AND full_content <> ''
          AND content_preview IS NOT NULL
        ORDER BY id
    '''
    if args.limit:
        sql += f' LIMIT {args.limit}'
    cur.execute(sql)
    records = cur.fetchall()
    print(f'→ 待处理: {len(records)} 条\n')

    stats = {'updated': 0, 'unchanged': 0, 'skipped_equals_title': 0, 'no_change': 0}
    samples = []
    samples_bracket = 0
    samples_footer = 0

    for rid, title, old_cp, fc in records:
        new_cp = make_content_preview(fc or '', title or '', max_len=300)
        if not new_cp:
            continue  # fc 本身没内容, 不动
        if new_cp == old_cp:
            stats['no_change'] += 1
            continue
        if new_cp == title:
            stats['skipped_equals_title'] += 1
            continue

        # 更新
        if not args.dry_run:
            try:
                cur.execute(
                    '''INSERT INTO _cp_clean_backup (id, old_content_preview, new_content_preview, title)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (id) DO UPDATE SET
                           old_content_preview = EXCLUDED.old_content_preview,
                           new_content_preview = EXCLUDED.new_content_preview,
                           fixed_at = NOW()''',
                    (rid, old_cp[:500], new_cp[:500], title[:200])
                )
                cur.execute('UPDATE projects_cqggzy SET content_preview = %s WHERE id = %s', (new_cp, rid))
                stats['updated'] += 1
            except Exception as e:
                conn.rollback()
                print(f'  ❌ [{rid}] {e}')
                continue
        else:
            stats['updated'] += 1

        # 分类统计 (取样)
        if old_cp.startswith('【】') and not new_cp.startswith('【】'):
            samples_bracket += 1
        if ('渝公网安备' in old_cp) and ('渝公网安备' not in new_cp):
            samples_footer += 1

        if len(samples) < 8:
            samples.append((rid, old_cp[:80], new_cp[:80], title[:50]))

    if not args.dry_run:
        conn.commit()
    else:
        conn.rollback()
    conn.close()

    print(f'\n=== 汇总 ===')
    print(f'  ✅ 更新: {stats["updated"]}')
    print(f'  — 新旧相同: {stats["no_change"]}')
    print(f'  ⚠️ 新 cp == title (跳过): {stats["skipped_equals_title"]}')
    print()
    print(f'  规则 12 (剥【】) 修复: ~{samples_bracket} 条')
    print(f'  规则 13 (剥页脚) 修复: ~{samples_footer} 条')

    if samples:
        print(f'\n=== 变更样本 (前 8 条) ===')
        for rid, old, new, title in samples:
            print(f'\n  [{rid}] {title}')
            print(f'    旧: {old}')
            print(f'    新: {new}')

    if args.dry_run:
        print(f'\n⚠️ DRY-RUN: 未写 DB, 重跑不带 --dry-run 执行')
    else:
        print(f'\n✅ 已 COMMIT. 备份表 _cp_clean_backup 含所有改动.')


if __name__ == '__main__':
    main()
