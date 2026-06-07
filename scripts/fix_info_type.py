"""
根据 URL 中的 categoryNum（取前 9 位）重新分类 projects_cqggzy.info_type

分类映射（用户提供，2026-06-02）:
工程招投标:
  014001019 → 招标计划
  014001001 → 招标公告
  014001002 → 答疑补遗
  014001003 → 中标候选人公示
  014001004 → 中标结果公示
  014001021 → 终止公告
政府采购:
  014005001 → 采购公告
  014005002 → 变更公告
  014005004 → 采购结果公告
"""
import psycopg2, os, re

pwd = os.environ.get('DB_PASSWORD', 'root123')
conn = psycopg2.connect(host='postgres', user='root', password=pwd, dbname='tender_scraper')
cur = conn.cursor()

# 分类映射（取前 9 位）
CATEGORY_MAP = {
    '014001019': '招标计划',
    '014001001': '招标公告',
    '014001002': '答疑补遗',
    '014001003': '中标候选人公示',
    '014001004': '中标结果公示',
    '014001021': '终止公告',
    '014005001': '采购公告',
    '014005002': '变更公告',
    '014005004': '采购结果公告',
}


def classify(url):
    """从 URL 提取 categoryNum 前 9 位 → info_type"""
    if not url:
        return None, 'URL为空'
    m = re.search(r'categoryNum=(\d+)', url)
    if not m:
        return None, '无categoryNum'
    cat_num = m.group(1)
    prefix = cat_num[:9]  # 取前 9 位
    if prefix in CATEGORY_MAP:
        return CATEGORY_MAP[prefix], prefix
    return None, f'未知前缀:{prefix}'


# 全表扫描
cur.execute("SELECT id, url, info_type FROM projects_cqggzy")
rows = cur.fetchall()
print(f"总记录: {len(rows)}")

# 统计
from collections import Counter
old_counter = Counter()
new_counter = Counter()
unmapped = Counter()
updates = []

for row_id, url, old_type in rows:
    new_type, prefix = classify(url)
    old_counter[old_type] += 1
    if new_type:
        new_counter[new_type] += 1
    else:
        unmapped[prefix] += 1
    if new_type != old_type:
        updates.append((new_type, row_id))

print("\n=== 当前 info_type 分布 ===")
for t, c in old_counter.most_common():
    print(f"  {t}: {c}")

print("\n=== 修正后 info_type 分布 ===")
for t, c in new_counter.most_common():
    print(f"  {t}: {c}")

print("\n=== 未匹配 categoryNum ===")
for p, c in unmapped.most_common():
    print(f"  {p}: {c}")

print(f"\n=== 需要 UPDATE 记录: {len(updates)} 条 ===")

# 批量 UPDATE
if updates:
    # 分批
    BATCH = 500
    updated = 0
    for i in range(0, len(updates), BATCH):
        batch = updates[i:i+BATCH]
        args = ','.join(cur.mogrify("(%s,%s)", x).decode('utf-8') for x in batch)
        sql = f"UPDATE projects_cqggzy AS t SET info_type = c.info_type FROM (VALUES {args}) AS c(info_type, id) WHERE t.id = c.id"
        cur.execute(sql)
        updated += cur.rowcount
    conn.commit()
    print(f"✅ 实际更新: {updated} 条")

# 验证
cur.execute("SELECT info_type, COUNT(*) FROM projects_cqggzy GROUP BY info_type ORDER BY 2 DESC")
print("\n=== 验证：DB 当前 info_type ===")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]}")
