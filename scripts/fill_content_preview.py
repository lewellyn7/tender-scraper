"""回填 content_preview / full_content

对 projects_cqggzy 中 content_preview 为空的记录，逐条从详情页抓取正文并更新。
"""
import asyncio, re, sys
from urllib.parse import urljoin

import httpx
from loguru import logger

sys.path.insert(0, '/app')
from app.database import get_db

BASE_URL   = "https://www.cqggzy.com"
SEARCH_URL = f"{BASE_URL}/jyxx/transaction_detail.html"
BATCH_SIZE = 30          # 每批并发数
MAX_RETRIES = 2


def extract_text(html: str) -> str:
    """从详情页 HTML 中提取正文内容"""
    text = re.sub(r'(?s)<script[^>]*>.*?</script>', '', html)
    text = re.sub(r'(?s)<style[^>]*>.*?</style>',   '', text)
    text = re.sub(r'(?s)<!--.*?-->',               '', text)
    text = re.sub(r'(?s)<nav[^>]*>.*?</nav>',        '', text)
    text = re.sub(r'(?s)<footer[^>]*>.*?</footer>',  '', text)
    text = re.sub(r'(?s)<header[^>]*>.*?</header>', '', text)
    # 去掉所有 HTML 标签
    text = re.sub(r'<[^>]+>', ' ', text)
    # 合并空白
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'&#\d+;', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


async def fetch_detail(client: httpx.AsyncClient, url: str, retries: int = MAX_RETRIES) -> str:
    for attempt in range(retries + 1):
        try:
            resp = await client.get(url, timeout=15, follow_redirects=True)
            if resp.status_code == 200:
                return extract_text(resp.text)
            elif resp.status_code in (403, 429):
                await asyncio.sleep(2 ** attempt)
            else:
                return ""
        except Exception:
            if attempt < retries:
                await asyncio.sleep(1)
    return ""


async def process_batch(db, batch: list, sem: asyncio.Semaphore) -> tuple[int, int]:
    """抓取一批 URL，返回 (成功数, 失败数)"""
    async with sem:
        async with httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": SEARCH_URL,
            },
            timeout=httpx.Timeout(20.0, connect=8.0),
        ) as client:
            tasks = [fetch_detail(client, row["url"]) for row in batch]
            texts = await asyncio.gather(*tasks)

        cur = db._get_conn().conn.cursor()
        updated = 0
        for row, text in zip(batch, texts):
            if not text:
                continue
            preview = text[:500]
            full    = text[:5000]
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

        db._get_conn().conn.commit()
        cur.close()
        return updated, len(batch) - updated


async def run():
    db = get_db()
    conn = db._get_conn().conn

    # 只抓有 transaction_detail.html 格式的记录
    cur = conn.cursor()
    cur.execute(
        """
        SELECT url, title, info_type
        FROM projects_cqggzy
        WHERE publish_date >= '2026-01-01'
          AND info_type NOT IN ('工程建设', '政府采购')
          AND url LIKE '%%/transaction_detail.html'
          AND (content_preview IS NULL OR content_preview = '' OR full_content IS NULL OR full_content = '')
        ORDER BY info_type, publish_date DESC
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

        # 清除 API 缓存
        try:
            async with httpx.AsyncClient() as c:
                await c.post(
                    "http://tender-scraper-web:8000/api/cache/clear",
                    json={"internal_key": ""},
                    timeout=5
                )
        except Exception:
            pass

        await asyncio.sleep(1)

    logger.info(f"✅ 完成: 成功 {total_updated} 条, 失败 {total_failed} 条")


if __name__ == "__main__":
    asyncio.run(run())