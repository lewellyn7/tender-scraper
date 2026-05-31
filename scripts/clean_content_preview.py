#!/usr/bin/env python3
"""清洗 content_preview - 去除标题重复"""
import re, sys

sys.path.insert(0, '/app')
from app.database import get_db

def clean_preview(text: str, title: str = "") -> str:
    if not text:
        return text

    # 去除网站头部导航噪音
    text = re.sub(
        r'^.*?(?:您当前的位置|当前位置|当前位置：)\s*[:：].*?(【[^】]+】[\u4e00-\u9fa5a-zA-Z0-9]+)',
        r'\1', text, flags=re.DOTALL
    )
    text = re.sub(r'^重庆市公共资源交易网[^\n]*\n?', '', text)
    text = re.sub(r'【\s*关闭\s*】\s*', '', text)
    text = re.sub(r'【\s*我要打印\s*】\s*', '', text)
    text = re.sub(r'【\s*字号\s*.*?\s*】\s*', '', text)
    text = re.sub(r'【\s*大\s*中\s*小\s*】', '', text)

    # 去除底部噪音
    text = re.sub(
        r'(?:凡是对本次公告内容提出询问|招标人信息|采购人信息|采购经办人|采购代理机构|代理机构信息|代理机构经办人|联系人|联系电话|监督部门|备注).*$',
        '', text, flags=re.DOTALL
    )

    # 去除标题前缀（如果 content_preview 开头的文字与 title 高度重复则去除）
    if title:
        # 取 title 前30个字符作为锚点
        title_prefix = title[:30].strip()
        if title_prefix and len(title_prefix) >= 6:
            # 匹配 title 前10字符 + 可能的通配符 + 后面的内容
            # 如果 content_preview 以 title 开头（允许细微差异如括号内数字不同），则去除
            pattern = re.escape(title_prefix)
            # 允许标题中的数字/括号差异（消防 vs 消防一）
            pattern = pattern.replace(r'\[', r'\[').replace(r'\]', r'\]')
            # 去掉最后2-3个字符看是否是通用前缀
            for cut in [0, 2, 4]:
                p = title_prefix[:-cut] if cut else title_prefix
                if len(p) >= 6 and text.startswith(p):
                    text = text[len(p):]
                    break
            # 直接去掉 title 本身（前30字符）
            if text.startswith(title_prefix):
                text = text[len(title_prefix):]

    # 清理残留噪音
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    return '\n'.join(lines).strip()

def run():
    db = get_db()
    conn = db._get_conn().conn
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, content_preview FROM projects_cqggzy
        WHERE publish_date >= '2026-01-01'
          AND content_preview IS NOT NULL AND content_preview != ''
          AND title IS NOT NULL AND title != ''
        LIMIT 20000
    """)
    rows = cur.fetchall()
    if not rows:
        print("没有需要清洗的记录")
        return

    print(f"清洗 {len(rows)} 条标题重复...")
    updated = 0
    for row_id, title, content in rows:
        cleaned = clean_preview(content, title)
        if cleaned != content:
            cur2 = conn.cursor()
            cur2.execute(
                "UPDATE projects_cqggzy SET content_preview = %s WHERE id = %s",
                (cleaned[:500], row_id)
            )
            updated += 1
            cur2.close()

    conn.commit()
    print(f"✅ {updated} 条已更新")

if __name__ == "__main__":
    run()