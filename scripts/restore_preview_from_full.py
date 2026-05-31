#!/usr/bin/env python3
"""从 full_content 回填 content_preview 并彻底清洗"""
import re, sys

sys.path.insert(0, '/app')
from app.database import get_db

def clean(text: str, title: str = "") -> str:
    # 去除网站头部
    text = re.sub(r'^.*?(?:您当前的位置|当前位置)\s*[:：]?\s*', '', text, flags=re.DOTALL)
    text = re.sub(r'^重庆市公共资源交易网[^\n]*\n?', '', text)
    text = re.sub(r'^(?:首页|工程招投标|政府采购)[^>\n]*(?:\s*>\s*[^>\n]+)+[\n]?', '', text, flags=re.MULTILINE)
    # 去除按钮噪音
    text = re.sub(r'【\s*(?:字号\s*)?[大中小小大\s]*\s*】【?\s*', '', text)
    text = re.sub(r'【\s*(?:我要打印|关闭)\s*】', '', text)
    text = re.sub(r'【\s*信息时间[：:]?\s*\d{4}[-/]\d{2}[-/]\d{2}\s*】', '', text)
    text = re.sub(r'^(?:我要报名|查看详情)[^\n]*\n?', '', text, flags=re.MULTILINE)
    # 去除供应商必看等页头
    text = re.sub(r'^【供应商必看】[^】]*】\s*', '', text)
    text = re.sub(r'^【定稿】[^】]*】\s*', '', text)
    text = re.sub(r'^免责声明[：:]?\s*', '', text)
    # 去除联系方式
    text = re.sub(r'^八、?联系方式\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+[.、]\s*(?:采购人|代理机构|招标人|联系人)?[^\n]*\n?', '', text, flags=re.MULTILINE)
    # 去除标题重复
    if title:
        tp = title[:30].strip()
        for cut in [0, 2, 4]:
            p = tp[:-cut] if cut else tp
            if len(p) >= 6 and text.startswith(p):
                text = text[len(p):].strip()
                break
    # 合并空白
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    return '\n'.join(lines).strip()

def run():
    db = get_db()
    conn = db._get_conn().conn
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, full_content
        FROM projects_cqggzy
        WHERE publish_date >= '2026-01-01'
          AND full_content IS NOT NULL AND full_content != ''
          AND (content_preview IS NULL OR content_preview = '')
        LIMIT 20000
    """)
    rows = cur.fetchall()
    if not rows:
        print("没有需要回填的记录")
        return

    print(f"从 full_content 回填 {len(rows)} 条...")
    updated = 0
    for row_id, title, full in rows:
        cleaned = clean(full, title or "")
        if cleaned:
            cur2 = conn.cursor()
            cur2.execute(
                "UPDATE projects_cqggzy SET content_preview = %s WHERE id = %s",
                (cleaned[:500], row_id)
            )
            updated += cur2.rowcount
            cur2.close()

    conn.commit()
    print(f"✅ {updated} 条已回填清洗")

if __name__ == "__main__":
    run()