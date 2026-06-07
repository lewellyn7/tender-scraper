#!/usr/bin/env python3
"""批量更新 projects_cqggzy 的 URL 从旧格式到新格式"""
import re

import psycopg2

# 连接
conn = psycopg2.connect(
    host="postgres", port=5432, database="tender_scraper",
    user="root", password="root123"
)
cur = conn.cursor()

# 统计
cur.execute("""
    SELECT COUNT(*) FROM projects_cqggzy 
    WHERE url LIKE 'https://www.cqggzy.com/xxhz/%'
      AND url ~ '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
""")
uuid_count = cur.fetchone()[0]
print(f"UUID 格式旧 URL: {uuid_count} 条")

cur.execute("""
    SELECT COUNT(*) FROM projects_cqggzy 
    WHERE url LIKE 'https://www.cqggzy.com/xxhz/%'
      AND url !~ '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
""")
num_count = cur.fetchone()[0]
print(f"数字 ID 格式旧 URL: {num_count} 条")

# categorynum 10位映射表（从 URL 路径解析）
# /xxhz/014001/014001001/014001001001/... → 014001001001
# /xxhz/014005/014005001/014005001001/... → 014005001001
CATNUM_MAP = {
    ('014001', '014001001'): '014001001001',
    ('014001', '014001019'): '014001019001',
    ('014001', '014001002'): '014001002001',
    ('014001', '014001003'): '014001003001',
    ('014001', '014001004'): '014001004001',
    ('014001', '014001021'): '014001021001',
    ('014005', '014005001'): '014005001001',
    ('014005', '014005002'): '014005002001',
    ('014005', '014005004'): '014005004001',
}

def convert_url(url: str) -> str | None:
    """将旧格式 URL 转换为新格式，返回 None 表示无法转换"""
    # 提取 trade_id (014001 或 014005)
    m = re.search(r'/xxhz/(01400[15])/', url)
    if not m:
        return None
    trade_id = m.group(1)

    # 提取 UUID（文件名部分）
    uuid_m = re.search(
        r'/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.html',
        url, re.IGNORECASE
    )
    if not uuid_m:
        return None
    uuid_val = uuid_m.group(1).lower()

    # 提取 categorynum 路径段（如 014001001001）
    cat_m = re.search(rf'/xxhz/{trade_id}/(\d{{3}})/(\d{{12}})/\d+/', url)
    if not cat_m:
        return None
    prefix = cat_m.group(1)  # 如 014001
    raw_catnum_12 = cat_m.group(2)  # 如 014001001001

    # 转换为 10 位
    catnum_10 = raw_catnum_12[:6] + '001'

    new_url = f"https://www.cqggzy.com/trade/{trade_id}/{uuid_val}?categoryNum={catnum_10}"
    return new_url

# 批量更新 UUID 格式
cur.execute("SELECT id, url FROM projects_cqggzy WHERE url LIKE 'https://www.cqggzy.com/xxhz/%' AND url ~ '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'")
rows = cur.fetchall()
updated = 0
for row_id, old_url in rows:
    new_url = convert_url(old_url)
    if new_url:
        cur.execute("UPDATE projects_cqggzy SET url=%s WHERE id=%s", (new_url, row_id))
        updated += 1

conn.commit()
print(f"UUID 格式已更新: {updated} 条")

# 数字 ID 格式：需要重新采集，跳过（打印样例）
cur.execute("SELECT id, url FROM projects_cqggzy WHERE url LIKE 'https://www.cqggzy.com/xxhz/%' AND url !~ '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' LIMIT 3")
for row_id, url in cur.fetchall():
    print(f"数字 ID 无法转换 (需重新采集): {url[:80]}")

cur.close()
conn.close()
print("完成")
