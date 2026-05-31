#!/usr/bin/env python3
"""清洗 content_preview - 彻底去除路径导航和项目名称重复"""
import re, sys

sys.path.insert(0, '/app')
from app.database import get_db

def clean_preview(text: str, title: str = "") -> str:
    if not text:
        return text

    # 1. 去除网站头部：重庆市公共资源交易网 + 您当前的位置 + 导航路径
    # 匹配从开头到第一个实际公告标题（以【信息时间或项目名或公告类型】开头）
    text = re.sub(
        r'^.*?(?:您当前的位置|当前位置)\s*[:：]?\s*',
        '',
        text,
        flags=re.DOTALL
    )
    # 去掉 "首页 > xxx > xxx > xxx" 导航行
    text = re.sub(r'^(?:首页|工程招投标|政府采购)[^>\n]*(?:\s*>\s*[^>\n]+)+[\n]?', '', text, flags=re.MULTILINE)
    # 去除 "重庆市公共资源交易网_重庆市公共资源交易中心" 残留
    text = re.sub(r'^重庆市公共资源交易网[^\n]*\n?', '', text)
    # 去除 【字号 大 中 小】【 我要打印】【 关闭】【信息时间：YYYY-MM-DD】
    text = re.sub(r'【\s*(?:字号\s*)?[大中小小大\s]*\s*】【?\s*', '', text)
    text = re.sub(r'【\s*(?:我要打印|关闭)\s*】', '', text)
    text = re.sub(r'【\s*信息时间[：:]?\s*\d{4}[-/]\d{2}[-/]\d{2}\s*】', '', text)
    # 去除 "我要报名" 等按钮残留
    text = re.sub(r'^(?:我要报名|查看详情|下载附件)[^\n]*\n?', '', text, flags=re.MULTILINE)
    # 去除底部的联系方式噪音
    text = re.sub(r'(?:八、?联系方式|1\.|采购人信息|代理机构信息|招标人信息|联系人[：:]?\s*\S+|联系电话[：:]?\s*\S+).*$',
                  '', text, flags=re.DOTALL)
    # 去除标题重复：content_preview 开头与 title（前40字）重复则去掉
    if title:
        for cut in [0, 1, 2, 3]:
            prefix = title[:40-cut].strip()
            if len(prefix) >= 8 and text.startswith(prefix):
                text = text[len(prefix):]
                break
    # 清理空白
    text = re.sub(r'\n{3,}', '\n\n', text)
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    return '\n'.join(lines).strip()

def run():
    db = get_db()
    conn = db._get_conn().conn
    cur = conn.cursor()
    # 只清洗含噪音的记录
    cur.execute("""
        SELECT id, title, content_preview FROM projects_cqggzy
        WHERE publish_date >= '2026-01-01'
          AND content_preview IS NOT NULL AND content_preview != ''
          AND (
            content_preview LIKE '%您当前的位置%'
            OR content_preview LIKE '%重庆市公共资源交易网%'
            OR content_preview LIKE '%信息时间%'
          )
        LIMIT 50000
    """)
    rows = cur.fetchall()
    if not rows:
        print("没有需要清洗的记录")
        return

    print(f"清洗 {len(rows)} 条记录...")
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
    print(f"✅ {updated} 条已清洗")

if __name__ == "__main__":
    run()