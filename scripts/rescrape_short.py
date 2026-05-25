#!/usr/bin/env python3
"""
补采短 content 的项目详情页（94-200 字符且非"详见附件"）
"""
import asyncio, sys, os
sys.path.insert(0, '/app')

from app.core.browser import StealthBrowser
from app.crawlers.cqggzy import CQGGZYCrawlerV2
from app.models.tender import TenderInfo
from loguru import logger
import psycopg2

logger.add("/dev/stderr", format="{time:HH:mm:ss} | {level: <8} | {message}", level="INFO", colorize=False)

def get_pg_conn():
    db_url = os.getenv("DATABASE_URL", "")
    if db_url.startswith("postgresql://"):
        return psycopg2.connect(dsn=db_url)
    return None

async def rescrape_short_content():
    conn = get_pg_conn()
    if not conn:
        logger.error("无法连接 PostgreSQL")
        return
    
    cur = conn.cursor()
    
    cur.execute("""
        SELECT url, title 
        FROM projects_cqggzy 
        WHERE LENGTH(full_content) BETWEEN 94 AND 200 
          AND full_content NOT LIKE %s
          AND full_content NOT LIKE %s
          AND full_content NOT LIKE %s
        ORDER BY created_at DESC
        LIMIT 20
    """, ('%详见附件%', '%CQCF%', '%工程量清单%'))
    
    rows = cur.fetchall()
    logger.info(f"待补采: {len(rows)} 条")
    
    if not rows:
        cur.close()
        conn.close()
        return
    
    browser = StealthBrowser(headless=True, slow_mo=5)
    await browser.start()
    crawler = CQGGZYCrawlerV2(browser)
    
    updated = 0
    for row_url, row_title in rows:
        try:
            logger.info(f"补采: {row_title[:40]}...")
            tender = TenderInfo(url=row_url, title=row_title)
            tender = await crawler._fetch_detail_page(tender)
            
            fc = tender.full_content or ""
            logger.info(f"  full_content: {len(fc)} 字")
            
            if len(fc) > 200:
                cp = fc[:500] + ("..." if len(fc) > 500 else "")
                cur.execute("""
                    UPDATE projects_cqggzy 
                    SET full_content = %s, content_preview = %s 
                    WHERE url = %s
                """, (fc, cp, row_url))
                conn.commit()
                updated += 1
                logger.info(f"  ✅ 更新成功 ({len(fc)} 字)")
            else:
                logger.warning(f"  ⚠️ 新内容仍较短: {len(fc)} 字")
        except Exception as e:
            logger.error(f"  ❌ 失败: {e}")
    
    await browser.close()
    cur.close()
    conn.close()
    logger.info(f"补采完成: {updated}/{len(rows)} 条更新")

if __name__ == "__main__":
    asyncio.run(rescrape_short_content())