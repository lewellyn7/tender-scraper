#!/usr/bin/env python3
"""从 projects_cqggzy/ccgp 的 title/full_content 提取 project_no 并回填"""

import re
import os
import sys

# 添加项目路径
sys.path.insert(0, '/app' if os.path.exists('/.dockerenv') else os.path.dirname(os.path.abspath(__file__)))

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://lewellyn:lewellyn@localhost:5435/tender_scraper"
)

PATTERNS = [
    re.compile(r"招标编号[：:]\s*([A-Z0-9][A-Z0-9\-]{3,31})", re.IGNORECASE),
    re.compile(r"项目编号[：:]\s*([A-Z0-9][A-Z0-9\-]{3,31})", re.IGNORECASE),
    re.compile(r"采购编号[：:]\s*([A-Z0-9][A-Z0-9\-]{3,31})", re.IGNORECASE),
    re.compile(r"\[([A-Za-z0-9][A-Za-z0-9\-]{3,35})\]"),
]


def extract_project_no(title: str, content: str = "") -> str:
    text = f"{title} {content or ''}"
    for pat in PATTERNS:
        m = pat.search(text)
        if m:
            pn = m.group(1).strip()
            # 过滤：至少6位，且不能是年号（如2026）或纯数字开头
            if pn and len(pn) >= 6 and not re.match(r"^\d{4}$", pn):
                return pn
    return ""


def main():
    import psycopg2

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False

    for table in ("projects_cqggzy", "projects_ccgp"):
        print(f"\n=== Processing {table} ===")
        cur = conn.cursor()

        # 批量获取 id, title, full_content
        cur.execute(f"SELECT id, title, COALESCE(full_content,'') FROM {table} ORDER BY id")
        rows = cur.fetchall()

        updates = []
        for row in rows:
            row_id, title, full_content = row
            pn = extract_project_no(title, full_content)
            if pn:
                updates.append((pn, row_id))

        cur.close()

        if not updates:
            print(f"  No project_no found")
            continue

        # 批量更新（每 100 条提交一次事务，避免长时间锁）
        cur2 = conn.cursor()
        updated = 0
        for pn, row_id in updates:
            cur2.execute(f"UPDATE {table} SET project_no = %s WHERE id = %s", (pn, row_id))
            updated += 1
            if updated % 200 == 0:
                conn.commit()
                print(f"  committed {updated}/{len(updates)}...")

        conn.commit()
        cur2.close()
        print(f"  Updated {updated} rows")

    # 统计
    cur3 = conn.cursor()
    for table in ("projects_cqggzy", "projects_ccgp"):
        cur3.execute(f"SELECT COUNT(*) FROM {table} WHERE project_no = '' OR project_no IS NULL")
        blank = cur3.fetchone()[0]
        cur3.execute(f"SELECT COUNT(*) FROM {table}")
        total = cur3.fetchone()[0]
        print(f"{table}: {total} total, {blank} still blank")

    cur3.close()
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()