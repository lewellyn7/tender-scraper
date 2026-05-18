#!/usr/bin/env python3
"""
补采脚本：重新抓取已入库记录的详情页，提取完整正文写入 full_content
绕过 DATABASE_URL，直接连接本地端口 5435

用法:
    python scripts/rescrape_full_content.py [--limit N] [--dry-run] [--business-type TYPE]
"""
import asyncio
import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import psycopg2
from playwright.async_api import async_playwright

# 直接连接本地 5435（docker 映射端口）
DB_URL = "postgresql://root:root123@localhost:5435/tender_scraper"


def get_db():
    return psycopg2.connect(DB_URL)


def fetch_projects(business_type="", min_len=0, limit=0, offset=0):
    """获取需要补采的记录（排除噪音路径）"""
    sql = """
        SELECT id, url, title, business_type, info_type,
               LENGTH(full_content) as content_len
        FROM projects_cqggzy
        WHERE url IS NOT NULL AND url != ''
          AND url !~ '/bszn/' AND url !~ '/zcfg/'
          AND LENGTH(full_content) < %s
    """
    params = [min_len or 3000]
    if business_type:
        sql += " AND business_type = %s"
        params.append(business_type)
    sql += " ORDER BY id"
    if offset > 0:
        sql += f" OFFSET {offset}"
    if limit > 0:
        sql += f" LIMIT {limit}"
    else:
        sql += " LIMIT 10000"

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def update_full_content(url, full_content, content_preview):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE projects_cqggzy
                SET full_content = %s, content_preview = %s
                WHERE url = %s
            """, (full_content, content_preview, url))
        conn.commit()


def count_needs_rescrape(business_type="", min_len=0):
    sql = """
        SELECT COUNT(*)
        FROM projects_cqggzy
        WHERE url IS NOT NULL AND url != ''
          AND url !~ '/bszn/' AND url !~ '/zcfg/'
          AND LENGTH(full_content) < %s
    """
    params = [min_len or 3000]
    if business_type:
        sql += " AND business_type = %s"
        params.append(business_type)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()[0]


async def scroll_page(page, max_polls=8):
    """滚动页面触发懒加载"""
    last_height = 0
    for _ in range(max_polls):
        try:
            await page.evaluate("""
                () => {
                    const el = document.querySelector('.content,.article,.detail-content,#content,.main-content,.zw_c,.con_r') || document.body;
                    el.scrollTop = el.scrollHeight;
                }
            """)
            await asyncio.sleep(0.8)
        except Exception:
            pass
        try:
            h = await page.evaluate("""
                () => {
                    const el = document.querySelector('.content,.article,.detail-content,#content,.main-content,.zw_c,.con_r');
                    return el ? el.scrollHeight : document.body.scrollHeight;
                }
            """)
            if h == last_height:
                break
            last_height = h
        except Exception:
            break
    await asyncio.sleep(0.5)


async def extract_text(page) -> tuple[str, str]:
    """从页面提取 full_content 和 content_preview"""
    try:
        body_text = await page.inner_text("body")
        # 识别正文区间：第一个含"项目"或"招标"且>20字符的行 → 最后一个含实际内容的行
        skip_kw = ["首 页", "重要通知", "交易信息", "收藏",
                   "您当前的位置", "sitemap", "关闭", "给我写信"]
        url_kw = ["cqggzy.com", "ccgp-chongqing.gov.cn", "qiatan.com"]

        lines = body_text.split("\n")
        content_lines = []
        in_body = False

        for line in lines:
            line = line.strip()
            # 导航/页脚噪声行
            if any(s in line for s in skip_kw):
                continue
            if line.startswith("http") and any(u in line for u in url_kw):
                continue
            # 跳过极短行（除非是章节标题）
            if len(line) < 4 and not any(c in line for c in ["、", "。", "："]):
                continue
            if len(line) < 8:
                continue

            if "项目" in line or "招标" in line or "采购" in line or "投标" in line:
                in_body = True

            if in_body:
                content_lines.append(line)

        full = "\n".join(content_lines)
        if len(full) >= 100:
            preview = full[:500] + "..." if len(full) > 500 else full
            return full, preview
    except Exception:
        pass

    return "", ""


async def scrape_one(browser, url, dry_run=False):
    try:
        page = await browser.new_page()
        await page.goto(url, timeout=30000, wait_until="networkidle")
        await asyncio.sleep(2)
        full, preview = await extract_text(page)
        await page.close()
        return full, preview
    except Exception as e:
        return "", ""


CHROMIUM_PATH = os.environ.get("CHROMIUM_PATH", "/home/lewellyn/.cache/ms-playwright/chromium-1117/chrome-linux/chrome")

async def main():
    parser = argparse.ArgumentParser(description="补采 full_content 完整正文")
    parser.add_argument("--limit", type=int, default=0, help="限制条数（0=全部）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入")
    parser.add_argument("--business-type", default="", help="政府采购/工程招投标")
    parser.add_argument("--min-len", type=int, default=3000, help="最小 full_content 长度（低于此值重采）")
    parser.add_argument("--offset", type=int, default=0, help="跳过前N条（断点续采）")
    args = parser.parse_args()
    rows = fetch_projects(business_type=args.business_type, min_len=args.min_len, limit=args.limit, offset=args.offset)
    total = count_needs_rescrape(business_type=args.business_type, min_len=args.min_len)

    if not rows:
        print("没有需要补采的记录")
        return

    print(f"总待补采: {total} 条，脚本取: {len(rows)} 条" + (" [DRY-RUN]" if args.dry_run else ""))
    print(f"参数: business_type={args.business_type!r}, min_len={args.min_len}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path=CHROMIUM_PATH)


        ok, fail = 0, 0
        for i, (rid, url, title, bt, it, clen) in enumerate(rows, 1):
            full, preview = await scrape_one(browser, url, dry_run=args.dry_run)
            if not full:
                print(f"[{i}/{len(rows)}] id={rid} FAIL (无内容) {title[:40]}")
                fail += 1
                continue

            if not args.dry_run:
                update_full_content(url, full, preview)

            print(f"[{i}/{len(rows)}] id={rid} OK {len(full)} chars {'[DRY]' if args.dry_run else 'saved'} | {title[:50]}")
            ok += 1

        await browser.close()

    print(f"\n完成: {ok} 成功 / {fail} 失败")


if __name__ == "__main__":
    asyncio.run(main())
