#!/usr/bin/env python3
"""回填 + 清洗 content_preview（一次遍历，避免重复写入）"""
import asyncio, re, sys

import httpx
from loguru import logger

sys.path.insert(0, '/app')
from app.database import get_db

BATCH_SIZE = 30
MAX_RETRIES = 2

def extract_and_clean(html: str, title: str = "") -> str:
    """从 HTML 提取正文并清洗"""
    # 去除脚本/样式/注释/nav/footer/header
    text = re.sub(r'(?s)<script[^>]*>.*?</script>', '', html)
    text = re.sub(r'(?s)<style[^>]*>.*?</style>',   '', text)
    text = re.sub(r'(?s)<!--.*?-->',               '', text)
    text = re.sub(r'(?s)<nav[^>]*>.*?</nav>',        '', text)
    text = re.sub(r'(?s)<footer[^>]*>.*?</footer>',  '', text)
    text = re.sub(r'(?s)<header[^>]*>.*?</header>', '', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    # HTML 实体
    text = text.replace('\xa0', ' ').replace('&nbsp;', ' ')
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'&#\d+;', '', text)
    # 去除网站头部导航
    text = re.sub(
        r'^.*?(?:您当前的位置|当前位置|当前位置：)\s*[:：].*?(【[^】]+】[\u4e00-\u9fa5a-zA-Z0-9]+)',
        r'\1', text, flags=re.DOTALL
    )
    text = re.sub(r'^重庆市公共资源交易网[^\n]*\n?', '', text)
    # 去除页脚噪音
    text = re.sub(
        r'(?:凡是对本次公告内容提出询问|招标人信息|采购人信息|采购经办人|采购代理机构|代理机构信息|代理机构经办人|联系人|联系电话|监督部门|备注).*$',
        '', text, flags=re.DOTALL
    )
    # 去除打印相关
    text = re.sub(r'【\s*关闭\s*】\s*', '', text)
    text = re.sub(r'【\s*我要打印\s*】\s*', '', text)
    text = re.sub(r'【\s*字号\s*.*?\s*】\s*', '', text)
    text = re.sub(r'【\s*大\s*中\s*小\s*】', '', text)
    # 去除标题重复（前30字符）
    if title:
        tp = title[:30].strip()
        if len(tp) >= 6 and text.startswith(tp):
            text = text[len(tp):]
    # 合并空白
    text = re.sub(r'[ \t]{2,}', ' ', text)
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    return '\n'.join(lines).strip()

async def fetch_detail(client: httpx.AsyncClient, url: str, retries: int = MAX_RETRIES) -> str:
    for attempt in range(retries + 1):
        try:
            resp = await client.get(url, timeout=15, follow_redirects=True)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code in (403, 429):
                await asyncio.sleep(2 ** attempt)
            else:
                return ""
        except Exception:
            if attempt < retries:
                await asyncio.sleep(1)
    return ""

async def process_batch(db, batch: list, sem: asyncio.Semaphore) -> tuple[int, int]:
    async with sem:
        async with httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.cqggzy.com/",
            },
            timeout=httpx.Timeout(20.0, connect=8.0),
        ) as client:
            tasks = [fetch_detail(client, row["url"]) for row in batch]
            raw_texts = await asyncio.gather(*tasks)

        conn = db._get_conn().conn
        cur = conn.cursor()
        updated = 0
        for row, raw in zip(batch, raw_texts):
            if not raw:
                continue
            cleaned = extract_and_clean(raw, row.get("title", ""))
            if not cleaned:
                continue
            preview = cleaned[:500]
            full    = cleaned[:5000]
            cur.execute(
                """
                UPDATE projects_cqggzy
                SET content_preview = %s, full_content = %s
                WHERE url = %s
                  AND (content_preview IS NULL OR content_preview = '' OR full_content IS NULL OR full_content = '')
                """,
                (preview, full, row["url"])
            )
            updated += cur.rowcount
        conn.commit()
        cur.close()
        return updated, len(batch) - updated

async def run():
    db = get_db()
    conn = db._get_conn().conn
    cur = conn.cursor()
    cur.execute(
        """
        SELECT url, title, info_type
        FROM projects_cqggzy
        WHERE publish_date >= '2026-01-01'
          AND url LIKE '%%cqggzy.com%%'
          AND info_type NOT IN ('工程建设', '政府采购')
          AND (content_preview IS NULL OR content_preview = '' OR full_content IS NULL OR full_content = '')
        ORDER BY publish_date DESC
        LIMIT 50000
        """
    )
    rows = cur.fetchall()
    cur.close()

    if not rows:
        logger.info("没有需要回填的记录")
        return

    records = [{"url": r[0], "title": r[1], "info_type": r[2]} for r in rows]
    logger.info(f"共 {len(records)} 条记录需要回填")

    sem = asyncio.Semaphore(BATCH_SIZE)
    total_updated = 0
    total_failed  = 0

    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        updated, failed = await process_batch(db, batch, sem)
        total_updated += updated
        total_failed  += failed
        logger.info(f"批次 {i//BATCH_SIZE + 1}: 成功 {updated}, 失败 {failed} | 累计成功 {total_updated}")
        await asyncio.sleep(1)

    logger.info(f"✅ 完成: 成功 {total_updated} 条, 失败 {total_failed} 条")

if __name__ == "__main__":
    asyncio.run(run())