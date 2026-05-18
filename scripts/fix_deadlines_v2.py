#!/usr/bin/env python3
"""直接修复 submission_deadline 中仍含原始文本的记录"""
import re, sys, os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app.database.db import Database
from app.utils.summarize import _clean_deadline, clean as text_clean

DB_URL = os.getenv("DATABASE_URL", "postgresql://root:root123@localhost:5435/tender_scraper")


def _strip_prefix(raw: str) -> str:
    raw = re.sub(r'^投标截止时间[，,\s]下同[\\)）]\s*', '', raw)
    raw = re.sub(r'^投标(?:文件)?递交截止(?:时间)?[：::]?\s*', '', raw)
    raw = re.sub(r'^[（(][^）)]*下同[）)][：:]*\s*', '', raw)
    raw = re.sub(r'^截止时间[）)：::]?\s*', '', raw)
    raw = re.sub(r'^：\s*', '', raw)
    raw = raw.strip()
    raw = re.sub(r'^为\s*', '', raw)
    return raw


def parse_date_from_text(text: str):
    """在任意位置找日期并清洗"""
    if not text:
        return None
    # 通用日期模式：4位年 + 分隔符 + 1-2位月 + 分隔符 + 1-2位日
    # 允许月/日之间有 \xa0 (不间断空格)
    patterns = [
        r'(\d{4})\s*[年\-]\s*(\d{1,2})\s*[月\-]\s*(\d{1,2})\s*日?\s*(?:(\d{1,2})\s*[时:：]\s*(\d{1,2}))?',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            hour, minute = m.group(4), m.group(5)
            result = f"{year}-{month:02d}-{day:02d}"
            if hour and minute:
                result += f" {int(hour):02d}:{int(minute):02d}"
            return result
    return None


def build_gov_overview(deadline, content):
    lines = []
    if deadline:
        lines.append(f"📌 投标截止时间：{deadline}")
    for pat in [
        r'(?:预算|最高限价|采购预算|采购最高限价)[：:]\s*([^\n]{1,80})',
        r'(?:预算金额|控制价)[：:]\s*([^\n]{1,80})',
    ]:
        m = re.search(pat, content)
        if m:
            val = text_clean(m.group(1))
            if val and val not in ('元', '人民币', ''):
                lines.append(f"💰 {val}")
                break
    m = re.search(r'(?:采购方式|组织形式)[：:]\s*([^\n]{2,30})', content)
    if m:
        val = text_clean(m.group(1))
        if val:
            lines.append(f"📋 {val}")
    m = re.search(r'(?:采购项目名称|项目名称|本次采购内容|采购内容|采购标的)[：:]\s*([^\n]{5,200})', content)
    if m:
        val = text_clean(m.group(1))
        if val:
            lines.append(f"📖 {val[:150]}")
    m = re.search(r'[^\n]*?(?:采购|标的)[^\n]*?元[^\n]*', content)
    if m:
        val = text_clean(m.group(0)[:200])
        if val and '元' in val:
            lines.append(f"📦 {val}")
    m = re.search(r'(?:采购人|联系人|电话)[：:]\s*([^\n]{2,50})', content)
    if m:
        val = text_clean(m.group(1))
        if val and len(val) > 2:
            lines.append(f"📞 {val[:60]}")
    return '\n'.join(lines).strip() or (f"📌 投标截止时间：{deadline}" if deadline else "无有效信息")


def build_eng_overview(deadline, content):
    lines = []
    if deadline:
        lines.append(f"📌 投标截止时间：{deadline}")
    for pat in [
        r'(?:招标控制价|最高限价|建安费|项目总投资|货物采购估算金额)[：:]\s*([^\n]{1,100})',
        r'(?:控制价|限价|总投资)[：:]\s*([^\n]{1,100})',
    ]:
        m = re.search(pat, content)
        if m:
            val = text_clean(m.group(1))
            if val and val not in ('元', '人民币', ''):
                lines.append(f"💰 {val}")
                break
    m = re.search(r'(?:招标范围|施工范围|本次招标项目)[：:]\s*([^\n]{10,300})', content)
    if m:
        val = text_clean(m.group(1))
        if val:
            lines.append(f"🎯 {val[:200]}")
    m = re.search(r'(?:建设规模|项目规模|项目概况)[：:]\s*([^\n]{5,200})', content)
    if m:
        val = text_clean(m.group(1))
        if val:
            lines.append(f"🏗️ {val[:150]}")
    m = re.search(r'(?:招标人|项目业主|建设单位)[：:]\s*([^\n]{2,60})', content)
    if m:
        val = text_clean(m.group(1))
        if val:
            lines.append(f"🏢 {val[:80]}")
    return '\n'.join(lines).strip() or (f"📌 投标截止时间：{deadline}" if deadline else "无有效信息")


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 直接修复 raw deadline...")
    db = Database(DB_URL)
    conn = db._get_conn()
    cur = conn.cursor()

    # 只查 submission_deadline 不是纯日期的记录
    cur.execute("""
        SELECT id, business_type, info_type, submission_deadline, full_content
        FROM projects_cqggzy
        WHERE (business_type = '政府采购' AND info_type = '采购公告')
           OR (business_type = '工程招投标' AND info_type = '招标公告')
          AND submission_deadline !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
        ORDER BY id
    """)
    rows = cur.fetchall()
    print(f"共 {len(rows)} 条 raw deadline 待修复")

    for row in rows:
        row_id, biz_type, info_type = row[0], row[1], row[2]
        sub_deadline = row[3] or ""
        content = row[4] or ""

        try:
            # 从 sub_deadline 自身直接解析日期
            new_deadline = parse_date_from_text(sub_deadline)
            if not new_deadline:
                # fallback: 尝试从 content 解析
                new_deadline = parse_date_from_text(content)

            # 生成 overview
            if biz_type == '政府采购':
                new_overview = build_gov_overview(new_deadline, content)
            else:
                new_overview = build_eng_overview(new_deadline, content)

            cur.execute("""
                UPDATE projects_cqggzy
                SET submission_deadline = %s, project_overview = %s, updated_at = NOW()
                WHERE id = %s
            """, (new_deadline or sub_deadline, new_overview, row_id))

        except Exception as e:
            print(f"  ⚠️ ID={row_id}: {e}")

    conn.commit()
    cur.close()
    print(f"✅ 完成")


if __name__ == "__main__":
    main()