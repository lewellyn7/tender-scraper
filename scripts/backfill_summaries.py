#!/usr/bin/env python3
"""
回填 projects_cqggzy 的 project_overview / content_preview
基于现有字段拼接结构化摘要

用法: python scripts/backfill_summaries.py [--run]
"""
import argparse
import os
import psycopg2


def make_summary(row: dict) -> dict:
    """根据 info_type 拼接 project_overview 和 content_preview"""
    info_type = row.get('info_type', '')
    title = row.get('title', '')
    budget = row.get('budget', '')
    deadline = row.get('deadline', '')
    region = row.get('region', '')
    bidder_req = row.get('bidder_requirements', '')
    contact_name = row.get('contact_name', '')
    contact_phone = row.get('contact_phone', '')
    bid_amount = row.get('bid_amount', '')
    submission_deadline = row.get('submission_deadline', '')

    lines = [title, '']

    if budget:
        lines.append(f"预算金额：{budget}")

    if deadline:
        lines.append(f"截止时间：{deadline}")
    elif submission_deadline:
        lines.append(f"截止时间：{submission_deadline}")

    if region:
        lines.append(f"采购地区：{region}")

    if bidder_req and bidder_req not in (title, budget):
        lines.append(f"资格要求：{bidder_req[:200]}")

    if contact_name:
        c = f"联系人：{contact_name}"
        if contact_phone:
            c += f" {contact_phone}"
        lines.append(c)

    # info_type 特定字段
    if info_type == '中标结果公示' and bid_amount:
        lines.append(f"中标金额：{bid_amount}")
    elif info_type == '中标候选人公示' and bid_amount:
        lines.append(f"预算金额：{bid_amount}")

    overview = '\n'.join(lines).strip()

    # content_preview 与 overview 基本相同，去掉标题简化
    preview_lines = [l for l in lines[1:] if l]  # 去掉标题行
    preview = '\n'.join(preview_lines[:5]).strip()

    return overview, preview


def main():
    parser = argparse.ArgumentParser(description="回填内容摘要")
    parser.add_argument("--run", action="store_true", help="正式写入（不加则干跑）")
    args = parser.parse_args()

    pg_url = os.getenv(
        "DATABASE_URL",
        "postgresql://root:root123@localhost:5435/tender_scraper"
    )
    conn = psycopg2.connect(pg_url)
    cursor = conn.cursor()

    # 查出所有需要回填的记录
    cursor.execute("""
        SELECT id, info_type, title, budget, deadline, region,
               bidder_requirements, contact_name, contact_phone,
               bid_amount, submission_deadline,
               project_overview, content_preview
        FROM projects_cqggzy
        WHERE project_overview IS NULL OR project_overview = ''
    """)
    rows = cursor.fetchall()
    cols = [d[0] for d in cursor.description]
    records = [dict(zip(cols, r)) for r in rows]

    print(f"待回填记录: {len(records)} 条")

    if not args.run:
        print("\n前 5 条预览:")
        for r in records[:5]:
            overview, preview = make_summary(r)
            print(f"  [{r['info_type']}] {r['title'][:40]}")
            print(f"    overview: {overview[:80]}")
            print(f"    preview:  {preview[:80]}")
            print()
        print("加 --run 正式写入")
        return

    # 正式写入
    updated = 0
    for r in records:
        overview, preview = make_summary(r)
        cursor.execute("""
            UPDATE projects_cqggzy
            SET project_overview = %s, content_preview = %s
            WHERE id = %s
        """, (overview, preview, r['id']))
        updated += 1

    conn.commit()
    print(f"✅ 已回填 {updated} 条")

    # 验证
    cursor.execute("SELECT COUNT(*) FROM projects_cqggzy WHERE project_overview IS NOT NULL AND project_overview != ''")
    print(f"   project_overview 非空: {cursor.fetchone()[0]} 条")
    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
