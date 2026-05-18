#!/usr/bin/env python3
"""修复 cqggzy 'tmp' 标题：直接从详情页提取真实标题"""
import asyncio, re, sys, os, httpx
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))
from app.database import get_db

async def fetch_real_title(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url)
            m = re.search(r'<h3\s+class="article-title">(.*?)</h3>', r.text)
            if m:
                return m.group(1).strip()
            # fallback: 从 <title> 标签提取
            m2 = re.search(r'<title>(.*?)</title>', r.text)
            if m2:
                t = m2.group(1).strip()
                if "重庆市公共资源交易网" not in t and len(t) > 5:
                    return t
    except Exception as e:
        print(f"  ⚠️ {url}: {e}", file=sys.stderr)
    return None

async def main():
    # 读取环境变量
    import dotenv
    dotenv.load_dotenv(Path(__file__).parent / ".env")

    db = get_db()
    cur = db.execute("SELECT id, url FROM projects_cqggzy WHERE title LIKE '待修复-%'")
    rows = cur.fetchall()
    print(f"找到 {len(rows)} 条待修复记录")
    
    updated = 0
    for row in rows:
        id_, url = row
        title = await fetch_real_title(url)
        if title and len(title) > 5:
            db.execute("UPDATE projects_cqggzy SET title = %s WHERE id = %s", (title, id_))
            updated += 1
            print(f"  ✅ {title[:50]}")
        else:
            print(f"  ❌ 无法获取: {url}")
    
    db.commit()
    print(f"\n修复完成: {updated}/{len(rows)}")

if __name__ == "__main__":
    asyncio.run(main())