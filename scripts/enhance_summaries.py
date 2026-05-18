#!/usr/bin/env python3
"""
从标题中提取结构化信息，丰富 project_overview
用法: python scripts/enhance_summaries.py [--run]
"""
import argparse
import os
import re
import psycopg2

# 项目编号正则
PROJECT_NO_RE = re.compile(r'[\(（]([A-Z]{2,4}\d{2}[A-Z]?\d{4,8})[\)）]')
# 采购方式
METHOD_RE = re.compile(r'(公开招标|竞争性磋商|竞争性谈判|询价采购|单一来源|邀请招标|比选)')
# 采购类型
TYPE_RE = re.compile(r'(系统集成|软件开发|网络设备|办公设备|物业管理|安保服务|咨询服务|规划设计|工程监理|装修工程|信息化建设|智能化|数字化)')


def enhance_from_title(title: str, info_type: str) -> str:
    """从标题中提取有用信息，拼接为摘要"""
    parts = []
    if not title:
        return ''

    # 提取项目编号
    m = PROJECT_NO_RE.search(title)
    project_no = m.group(1) if m else ''
    if project_no:
        parts.append(f"项目编号：{project_no}")

    # 提取采购方式
    m = METHOD_RE.search(title)
    method = m.group(1) if m else ''
    if method:
        parts.append(f"采购方式：{method}")

    # 提取采购类型
    types_found = TYPE_RE.findall(title)
    if types_found:
        parts.append(f"采购类别：{'、'.join(types_found)}")

    # 信息类型说明
    type_hints = {
        '招标公告': '报名进行中',
        '采购公告': '公告发布',
        '答疑补遗': '澄清答疑',
        '中标候选人公示': '评审完成',
        '中标结果公示': '结果确定',
        '招标计划': '计划阶段',
        '终止公告': '已终止',
        '相关公告': '其他',
    }
    if info_type in type_hints:
        parts.append(f"状态：{type_hints[info_type]}")

    # 来源平台
    parts.append('来源：重庆市公共资源交易网')

    return ' | '.join(parts) if parts else ''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()

    pg_url = os.getenv("DATABASE_URL", "postgresql://root:root123@localhost:5435/tender_scraper")
    conn = psycopg2.connect(pg_url)
    cur = conn.cursor()

    # 查出所有有标题的记录
    cur.execute("SELECT id, title, info_type, project_overview FROM projects_cqggzy")
    rows = cur.fetchall()

    to_update = []
    for row in rows:
        rid, title, info_type, overview = row
        enhanced = enhance_from_title(title or '', info_type or '')
        if enhanced:
            # 追加到现有 overview
            new_overview = (overview + '\n' + enhanced).strip() if overview else enhanced
            to_update.append((new_overview, rid))

    print(f"可增强记录: {len(to_update)} 条")

    if not args.run:
        # 预览前 5 条
        for new_ov, (rid, title, it, old_ov) in zip(
                [t[0] for t in to_update[:5]],
                [(r[0], r[1], r[2], r[3]) for r in rows[:5]]
            ):
            print(f"\n标题: {title[:50]}")
            print(f"  原摘要: {str(old_ov)[:50]}")
            print(f"  新摘要: {new_ov[:100]}")
        print("\n加 --run 正式写入")
        return

    for new_ov, rid in to_update:
        cur.execute("UPDATE projects_cqggzy SET project_overview = %s WHERE id = %s", (new_ov, rid))

    conn.commit()
    print(f"✅ 增强 {len(to_update)} 条")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
