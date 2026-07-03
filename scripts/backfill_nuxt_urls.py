#!/usr/bin/env python3
"""7-03 回填: 修复 NUXT fallback 路径写入的搜索页 URL (?title=) → 真实详情页 URL.

发现 cqggzy.py 在 NUXT fallback 路径 line 411-412 用占位 URL:
    f"https://www.cqggzy.com/trade/0XXXXX?title={title[:20]}"
而不是从 NUXT_DATA 中提取的 infoid (UUID) + categorynum 拼接的详情页 URL.

该脚本用于:
1. 扫描 DB 中 url 匹配 `/trade/0XXXXX?title=` 的错列
2. 从 source_url (list page URL) 重新抓 HTML
3. 用 _parse_nuxt_projects 解析 NUXT_DATA, 反查 title → infoid + categorynum
4. UPDATE DB url 为正确详情页 URL

用法:
    # dry-run (默认)
    python scripts/backfill_nuxt_urls.py

    # 实际执行 (修改 DB)
    python scripts/backfill_nuxt_urls.py --apply

    # 限制条数
    python scripts/backfill_nuxt_urls.py --apply --limit 10
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

# 把项目根目录加到 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
import requests
from loguru import logger

from app.crawlers.cqggzy import _parse_nuxt_projects  # noqa: E402

# 镜像采集器常量 (BASE_URL 是类属性, 直接用)
BASE_URL = "https://www.cqggzy.com"


# ── 配置 ────────────────────────────────────────────────────────────────────
WRONG_URL_PATTERN = re.compile(r"^https://www\.cqggzy\.com/trade/0\d+\?title=")

# DB 连接: 优先用 DATABASE_URL env (跟生产 web 容器一致),否则用默认 DSN
DB_DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://root:root123@postgres:5432/tender_scraper",
)

# 标题前 N 字作为快速匹配锚点 (防止 list page 改版后标题全模糊匹配)
TITLE_PREFIX_KEYWORD_FIRST = 10


def db_query(sql: str, params: tuple = ()):
    """执行 SQL (psycopg2 sync)."""
    conn = psycopg2.connect(DB_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description:
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            conn.commit()
            return []
    finally:
        conn.close()


def db_execute(sql: str, params: tuple = ()):
    """执行 UPDATE/INSERT 并返回 affected row count."""
    conn = psycopg2.connect(DB_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            affected = cur.rowcount
            conn.commit()
            return affected
    finally:
        conn.close()


def fetch_nuxt_text(source_url: str, *, timeout: int = 30) -> str:
    """抓取 source_url (list page) 的 HTML,返回 __NUXT_DATA__ 段.

    用 requests + 浏览器 User-Agent (CQGGZY 站点偶尔拒绝 bot UA).
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    resp = requests.get(source_url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    html = resp.text
    m = re.search(r'__NUXT_DATA__[^>]*>(.+?)</script>', html, re.DOTALL)
    if not m:
        raise RuntimeError(f"__NUXT_DATA__ not found in {source_url}")
    return m.group(1)


def match_project_in_projects(title: str, projects: list, source_url: str) -> dict | None:
    """从 _parse_nuxt_projects 输出的列表中精确匹配 title (前 12 字符锚点).

    防御误匹配: 用 title 前 12 字符(去全角符号)做精确锚点,
    防止 list page 含别的类似标题.
    """
    needle = re.sub(r"\s+", "", title[:12])  # 去空白
    for p in projects:
        if needle in re.sub(r"\s+", "", p["title"]):
            return p
    return None


def build_correct_url(linkurl: str, infoid: str, catnum: str) -> str:
    """拼接详情页 URL. 优先用 NUXT linkurl (路径最准)."""
    if linkurl and linkurl.startswith("/"):
        return f"{BASE_URL}{linkurl}"
    # trade_id 严格依据 catnum 前 6 位 (与 cqggzy.py 一致)
    if catnum.startswith("014001"):
        trade_id = "014001"
    elif catnum.startswith("014005"):
        trade_id = "014005"
    else:
        raise ValueError(f"unsupported catnum: {catnum}")
    return f"{BASE_URL}/trade/{trade_id}/{infoid}?categoryNum={catnum}"


def find_wrong_urls(limit: int | None = None) -> list:
    """扫描 projects_cqggzy 中 url 是搜索页模式的记录."""
    sql = """
        SELECT id, title, url, source_url, category, info_type, publish_date, scraped_at
        FROM projects_cqggzy
        WHERE url ~ '^https://www\\.cqggzy\\.com/trade/0\\d+\\?title='
        ORDER BY scraped_at DESC, id DESC
    """
    if limit:
        sql += " LIMIT %s"
        rows = db_query(sql, (limit,))
    else:
        rows = db_query(sql)
    return rows


def backfill_one(row: dict, dry_run: bool = True) -> dict:
    """回填单条. 返回 {ok, new_url, error}."""
    title = row["title"]
    source_url = row["source_url"]
    if not source_url:
        return {"id": row["id"], "ok": False, "error": "no source_url"}

    try:
        nuxt_text = fetch_nuxt_text(source_url)
    except Exception as e:
        return {"id": row["id"], "ok": False, "error": f"fetch failed: {e}"}

    projects = _parse_nuxt_projects(nuxt_text)
    matched = match_project_in_projects(title, projects, source_url)
    if not matched:
        return {
            "id": row["id"],
            "ok": False,
            "error": f"title not found in {len(projects)} projects (may have rotated out)",
        }

    new_url = build_correct_url(
        matched["linkurl"], matched["infoid"], matched["categorynum"]
    )

    if dry_run:
        return {"id": row["id"], "ok": True, "dry_run": True, "new_url": new_url}

    affected = db_execute(
        "UPDATE projects_cqggzy SET url = %s WHERE id = %s AND url ~ '^https://www\\.cqggzy\\.com/trade/0\\d+\\?title='",
        (new_url, row["id"]),
    )
    if affected == 0:
        return {"id": row["id"], "ok": False, "error": "UPDATE 0 rows (URL 不再匹配模式)"}
    return {"id": row["id"], "ok": True, "new_url": new_url, "affected": affected}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--apply", action="store_true", help="实际 UPDATE (默认 dry-run)")
    parser.add_argument("--limit", type=int, default=None, help="限制条数")
    args = parser.parse_args()

    dry_run = not args.apply

    rows = find_wrong_urls(limit=args.limit)
    print(f"找到 {len(rows)} 条 url 错误的记录 (dry-run={dry_run})\n")
    if not rows:
        return

    summary = {"ok": 0, "fail": 0, "errors": []}
    for i, row in enumerate(rows, 1):
        title_short = row["title"][:40]
        print(f"[{i}/{len(rows)}] id={row['id']} {title_short}...")
        result = backfill_one(row, dry_run=dry_run)
        if result.get("ok"):
            print(f"  ✅ {result.get('new_url', '')[:80]}")
            summary["ok"] += 1
        else:
            print(f"  ❌ {result.get('error')}")
            summary["fail"] += 1
            summary["errors"].append((row["id"], result.get("error")))
        time.sleep(0.5)  # 礼貌: 不连续请求

    print()
    print(f"=== {'Dry-run' if dry_run else '回填'}完成: ✅ {summary['ok']} / ❌ {summary['fail']} ===")
    if summary["errors"]:
        print()
        print("错误明细:")
        for id_, err in summary["errors"]:
            print(f"  id={id_}: {err}")


if __name__ == "__main__":
    main()
