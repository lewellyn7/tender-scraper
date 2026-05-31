#!/usr/bin/env python3
"""深度清洗 content_preview - 处理残留噪音和标题重复"""
import re, sys

sys.path.insert(0, '/app')
from app.database import get_db

def clean_preview(text: str, title: str = "") -> str:
    if not text:
        return text

    # 去除供应商必看等页头
    text = re.sub(r'^【供应商必看】[^】]*】\s*', '', text)
    text = re.sub(r'^【定稿】[^】]*】\s*', '', text)
    text = re.sub(r'^【正式版】[^】]*】\s*', '', text)
    text = re.sub(r'^免责声明[：:]?\s*', '', text)

    # 去除联系方式行
    text = re.sub(r'^八、?联系方式\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+[.、]\s*(?:采购人|代理机构|招标人|联系人)?[^\n]*\n?', '', text, flags=re.MULTILINE)
    text = re.sub(r'^(?:采购人信息|代理机构信息|招标人信息)[^\n]*\n?', '', text, flags=re.MULTILINE)
    text = re.sub(r'^(?:联系人|联系电话)[：:]?\s*[^\n]*', '', text, flags=re.MULTILINE)

    # 去除标题重复（模糊匹配前30字是否在开头出现）
    if title:
        # 提取标题前30字，去除括号内容（编号）
        clean_title = re.sub(r'\([^)]*\)', '', title).strip()
        prefix = clean_title[:30].strip()
        if len(prefix) >= 6:
            # 检查前40字符中是否包含标题（允许括号差异）
            head = text[:80]
            # 如果开头是标题的纯文本版本（无括号），去掉
            for cut in [0, 2, 4, 6]:
                p = prefix[:-cut] if cut else prefix
                if len(p) >= 6 and head.startswith(p):
                    text = text[len(p):].strip()
                    break
            # 如果标题（含括号）在开头，去掉
            if text.startswith(title[:20].strip()):
                text = text[len(title[:20].strip()):].strip()

    # 去除残留的网站导航碎片
    text = re.sub(r'^重庆市公共资源交易网[^\n]*\n?', '', text, flags=re.MULTILINE)
    text = re.sub(r'^您当前的位置[：:]?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^首页[ >][^\n]*\n?', '', text, flags=re.MULTILINE)

    # 清理空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    return '\n'.join(lines).strip()

def run():
    db = get_db()
    conn = db._get_conn().conn
    cur = conn.cursor()
    # 清洗所有非空 content_preview
    cur.execute("""
        SELECT id, title, content_preview FROM projects_cqggzy
        WHERE publish_date >= '2026-01-01'
          AND content_preview IS NOT NULL AND content_preview != ''
        LIMIT 50000
    """)
    rows = cur.fetchall()
    if not rows:
        print("没有需要清洗的记录")
        return

    print(f"深度清洗 {len(rows)} 条记录...")
    updated = 0
    for row_id, title, content in rows:
        cleaned = clean_preview(content, title or "")
        if cleaned != content:
            cur2 = conn.cursor()
            cur2.execute(
                "UPDATE projects_cqggzy SET content_preview = %s WHERE id = %s",
                (cleaned[:500], row_id)
            )
            updated += 1
            cur2.close()

    conn.commit()
    print(f"✅ {updated} 条已深度清洗")

if __name__ == "__main__":
    run()