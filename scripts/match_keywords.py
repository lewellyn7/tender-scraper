#!/usr/bin/env python3
"""基于 content_preview 补充 keywords_matched"""
import re, sys
from loguru import logger

sys.path.insert(0, '/app')
from app.database import get_db

def load_keywords(conn):
    cur = conn.cursor()
    cur.execute("SELECT keyword, category, match_mode, threshold FROM keywords WHERE enabled = 1")
    rows = cur.fetchall()
    cur.close()
    return [(r[0], r[1], r[2], r[3]) for r in rows]

def fuzzy_match(text: str, kw: str, threshold: float) -> bool:
    import difflib
    return difflib.SequenceMatcher(None, text, kw).ratio() >= threshold

def match_keywords(content: str, keywords) -> list:
    if not content:
        return []
    matched = []
    for kw, cat, mode, th in keywords:
        found = False
        if mode == 'exact':
            if kw in content:
                found = True
        elif mode == 'fuzzy':
            # 在 content 中搜索，与标题+内容做模糊匹配
            if fuzzy_match(content[:500], kw, th):
                found = True
        if found:
            matched.append((kw, cat))
    return matched

def run():
    db = get_db()
    conn = db._get_conn().conn

    keywords = load_keywords(conn)
    if not keywords:
        print("关键词表为空，请先填充")
        return

    print(f"加载 {len(keywords)} 个关键词")

    cur = conn.cursor()
    # 匹配 content_preview 非空但 keywords_matched 为空的记录
    cur.execute("""
        SELECT id, content_preview, title
        FROM projects_cqggzy
        WHERE publish_date >= '2026-01-01'
          AND content_preview IS NOT NULL
          AND content_preview != ''
          AND (keywords_matched IS NULL OR keywords_matched = '')
        LIMIT 30000
    """)
    rows = cur.fetchall()
    cur.close()

    if not rows:
        print("没有需要匹配的记录")
        return

    print(f"开始匹配 {len(rows)} 条记录...")
    updated = 0
    for row_id, content, title in rows:
        matched = match_keywords(content, keywords)
        if matched:
            # 排除 exclude 类别
            include_kws = [kw for kw, cat in matched if cat == 'include']
            if include_kws:
                cur2 = conn.cursor()
                cur2.execute(
                    "UPDATE projects_cqggzy SET keywords_matched = %s WHERE id = %s",
                    (','.join(include_kws), row_id)
                )
                updated += 1
                cur2.close()

    conn.commit()
    print(f"✅ 完成: {updated} 条已补充关键词")

if __name__ == "__main__":
    run()