#!/usr/bin/env python3
"""Regenerate summaries with fixed deadline parsing"""
import os, sys, re
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database.db import Database
from app.utils.summarize import _clean_deadline, clean as text_clean

DB_URL = os.getenv("DATABASE_URL", "postgresql://root:root123@localhost:5435/tender_scraper")


# ─── 截止时间提取模式 ─────────────────────────────────────────────────────────

DEADLINE_PATTERNS_GOV = [
    r'四、投标文件递交[^\n]*\n(?:[^\n]*\n){0,30}[^\n]*?截止[^\n]*?(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[日]?(?:\s*\d{1,2}[时:：]\d{1,2}(?:分|秒?)?)?)',
    r'投标文件递交截止时间[：:]\s*(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[日]?(?:\s*\d{1,2}[时:：]\d{1,2}(?:分|秒?)?)?)',
    r'(?:磋商|谈判|询价)响应文件递交截止时间[：:]\s*(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[日]?(?:\s*\d{1,2}[时:：]\d{1,2}(?:分|秒?)?)?)',
    r'递交(?:响应|投标|报价)?截止时间[：::]?\s*(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[日]?(?:\s*\d{1,2}[时:：]\d{1,2}(?:分|秒?)?)?)',
    r'截止时间[：:]\s*(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[日]?(?:\s*\d{1,2}[时:：]\d{1,2}(?:分|秒?)?)?)',
]

DEADLINE_PATTERNS_ENG = [
    r'5\.1[、.]\s*(?:投标文件递交的截止时间[（(]?[^）)]*?[）)]?[为:：]?\s*)?(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[日]?(?:\s*\d{1,2}[时:：]\d{1,2}(?:分|秒?)?)?)',
    r'6\.投标文件递交[^\n]*\n(?:[^\n]*\n){0,20}[^\n]*?(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[日]?(?:\s*\d{1,2}[时:：]\d{1,2}(?:分|秒?)?)?)',
    r'投标截止时间[，,\s]下同[）)]：?\s*(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[日]?(?:\s*\d{1,2}[时:：]\d{1,2}(?:分|秒?)?)?)',
    r'投标文件递交截止时间[：:]\s*(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[日]?(?:\s*\d{1,2}[时:：]\d{1,2}(?:分|秒?)?)?)',
    r'(?:投标)?截止时间[）：:]?\s*(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[日]?(?:\s*\d{1,2}[时:：]\d{1,2}(?:分|秒?)?)?)',
]


def _strip_prefix(raw: str) -> str:
    """去掉截止时间常见的各类前缀"""
    raw = re.sub(r'^投标截止时间[，,\s]下同[\\)）]\s*', '', raw)
    raw = re.sub(r'^投标(?:文件)?递交截止(?:时间)?[：::]?\s*', '', raw)
    raw = re.sub(r'^[（(][^）)]*下同[）)][：:]*\s*', '', raw)
    raw = re.sub(r'^截止时间[）)：::]?\s*', '', raw)
    raw = re.sub(r'^：\s*', '', raw)
    raw = raw.strip()
    # 去掉常见的前缀字（如"为2026"、"（下同）为"之后残留的"为"）
    raw = re.sub(r'^为\s*', '', raw)
    return raw


def extract_deadline(patterns, content, fallback=""):
    """用多模式依次提取截止时间，然后清洗"""
    if not content:
        return fallback
    for pat in patterns:
        m = re.search(pat, content)
        if m:
            raw = _strip_prefix(m.group(1))
            cleaned = _clean_deadline(raw)
            if cleaned:
                return cleaned
    return fallback


def build_gov_overview(deadline, content):
    """政府采购-采购公告 概述"""
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
    """工程招投标-招标公告 概述"""
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
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始重写摘要...")
    db = Database(DB_URL)
    conn = db._get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, business_type, info_type, full_content,
               submission_deadline, project_overview
        FROM projects_cqggzy
        WHERE (business_type = '政府采购' AND info_type = '采购公告')
           OR (business_type = '工程招投标' AND info_type = '招标公告')
        ORDER BY id
    """)
    rows = cur.fetchall()
    print(f"共 {len(rows)} 条记录待处理")

    updated = 0
    for row in rows:
        row_id, biz_type, info_type = row[0], row[1], row[2]
        content = row[3] or ""
        old_deadline = row[4] or ""
        old_overview = row[5] or ""

        try:
            if biz_type == '政府采购' and info_type == '采购公告':
                new_deadline = extract_deadline(DEADLINE_PATTERNS_GOV, content, old_deadline)
                new_overview = build_gov_overview(new_deadline, content)
            elif biz_type == '工程招投标' and info_type == '招标公告':
                new_deadline = extract_deadline(DEADLINE_PATTERNS_ENG, content, old_deadline)
                new_overview = build_eng_overview(new_deadline, content)
            else:
                continue

            if new_deadline != old_deadline or new_overview != old_overview:
                cur.execute("""
                    UPDATE projects_cqggzy
                    SET submission_deadline = %s, project_overview = %s, updated_at = NOW()
                    WHERE id = %s
                """, (new_deadline, new_overview, row_id))
                updated += 1
                if updated % 20 == 0:
                    conn.commit()

        except Exception as e:
            print(f"  ⚠️ ID={row_id}: {e}")

    conn.commit()
    cur.close()
    print(f"✅ 完成！更新 {updated} 条")


if __name__ == "__main__":
    main()
