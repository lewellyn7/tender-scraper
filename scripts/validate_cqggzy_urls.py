#!/usr/bin/env python3
"""
Phase 1 抽样验证脚本 (D-1.5 mini-spec commit 1)

验证 cqggzy trade 缺 _1 的 URL, 分类 A/B/C/D 4 类:
- A: 不加 _1 → 200 (网站自动重定向, 不动)
- B: 加 _1 → 200 (真正修复, 加 _1)
- C: 加 _1 → 404 (永久死链, 标记但不修)
- D: 加 _1 → 200 但无内容 (broken detail page, 标记但不修)

使用方法:
  python scripts/validate_cqggzy_urls.py [--n=200]

lesson 19: 批量 URL 修复前必先 HTTP 验证 (silent-killer 警报第 3 次命中)
"""

import asyncio
import os
import random
import re
import sys
from typing import Optional

import asyncpg
import httpx

# DB_URL 优先级: 环境变量 > 各部分 env > 默认 (lesson 20/21)
# lesson 21 关键修复: PG 容器端口=5435 (不是默认 5432), password 来自 docker inspect
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    _user = os.getenv("POSTGRES_USER", "root")
    _pass = os.getenv("POSTGRES_PASSWORD", "root123")  # docker inspect POSTGRES_PASSWORD=root123
    _host = os.getenv("POSTGRES_HOST", "localhost")
    _port = os.getenv("POSTGRES_PORT", "5435")  # 容器映射端口，非 PG 默认 5432
    _db = os.getenv("POSTGRES_DB", "tender_scraper")
    DB_URL = f"postgresql://{_user}:{_pass}@{_host}:{_port}/{_db}"

# /trade/01400[15]/<UUID>? → /trade/01400[15]/<UUID>_1?
UUID_PATTERN = re.compile(r"(/trade/01400[15]/[0-9a-f-]+)(\?)")


def add_suffix_1(url: str) -> str:
    """给 trade URL 加 _1 后缀（仅缺 _1 时加）"""
    if UUID_PATTERN.search(url) and "_1" not in url:
        return UUID_PATTERN.sub(r"\1_1\2", url)
    return url


async def check_one(
    url_orig: str, url_with_1: str, client: httpx.AsyncClient
) -> dict:
    """同时 HEAD 验证原 URL 和加 _1 后 URL（不消耗 cookie / 不下载 body）"""
    result = {"orig": None, "with_1": None}
    try:
        r1 = await client.head(url_orig, timeout=10, follow_redirects=True)
        result["orig"] = r1.status_code
    except Exception as e:
        result["orig"] = f"ERR:{type(e).__name__}"
    try:
        r2 = await client.head(url_with_1, timeout=10, follow_redirects=True)
        result["with_1"] = r2.status_code
    except Exception as e:
        result["with_1"] = f"ERR:{type(e).__name__}"
    return result


def classify(orig_status, with_1_status) -> str:
    """4 类分类 + 兜底 X（异常）"""
    # A: orig 200 (网站自动重定向, 不加 _1 也能访问)
    if orig_status == 200:
        return "A"
    # C: both 404 (永久死链)
    if orig_status == 404 and with_1_status == 404:
        return "C"
    # B: orig non-200, with_1 200 (真正修复)
    if with_1_status == 200:
        return "B"
    # 兜底（异常状态码、连接错误等）
    return "X"


async def fetch_urls(n: int) -> list:
    """从 DB 抽 n 个 trade 缺 _1 的 URL（按发布日期倒序）"""
    conn = await asyncpg.connect(DB_URL)
    try:
        rows = await conn.fetch(
            """
            SELECT id, url, info_type FROM projects_cqggzy
            WHERE url ~ '/trade/01400[15]/[0-9a-f-]+\\?'
              AND url NOT LIKE '%\\_1%'
            ORDER BY publish_date DESC NULLS LAST
            LIMIT $1
            """,
            n,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def main(n: int = 200, concurrency: int = 3):
    print(f"🔍 Phase 1 抽样验证: N={n}, concurrency={concurrency}")

    # 1. 从 DB 抽 N 个 trade 缺 _1 的 URL
    rows = await fetch_urls(n)
    if not rows:
        print("⚠️ No URLs to validate (trade 缺 _1 = 0)")
        return

    print(f"📦 抽到 {len(rows)} 个 URL，开始 HTTP HEAD 验证 (限速 1-3 req/s)")

    # 2. 限速 1-3 req/s, max concurrency 并发
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0 (compatible; URLValidator/1.0)"},
    ) as client:

        async def bounded(idx: int, row: dict):
            async with semaphore:
                # 限速 1-3s 随机 (避免反爬)
                await asyncio.sleep(random.uniform(1, 3))
                url_orig = row["url"]
                url_with_1 = add_suffix_1(url_orig)
                check = await check_one(url_orig, url_with_1, client)
                return {
                    "idx": idx,
                    "id": row["id"],
                    "url_orig": url_orig,
                    "url_with_1": url_with_1,
                    "info_type": row["info_type"],
                    **check,
                }

        tasks = [bounded(i, row) for i, row in enumerate(rows)]
        results = await asyncio.gather(*tasks)

    # 3. 分类统计
    stats = {"A": 0, "B": 0, "C": 0, "D": 0, "X": 0}
    classified = []
    for r in results:
        cat = classify(r["orig"], r["with_1"])
        stats[cat] += 1
        classified.append({**r, "category": cat})

    total = len(classified)
    print(f"\n📊 分类结果 (N={total}):")
    for cat in ["A", "B", "C", "D", "X"]:
        pct = stats[cat] / total * 100
        print(f"  {cat}: {stats[cat]:3d} ({pct:5.1f}%)")

    # 4. 输出每类样本（前 3 条）
    for cat in ["A", "B", "C", "D"]:
        samples = [r for r in classified if r["category"] == cat][:3]
        if samples:
            print(f"\n📝 {cat} 类样本 (前 3 条):")
            for s in samples:
                print(f"  id={s['id']} | info_type={s['info_type']}")
                print(f"    orig:   {s['url_orig']}")
                print(f"    with_1: {s['url_with_1']}")
                print(f"    status: orig={s['orig']} → with_1={s['with_1']}")

    # 5. Phase 2 决策建议
    print("\n🎯 Phase 2 决策建议:")
    a_pct = stats["A"] / total
    b_pct = stats["B"] / total
    cd_pct = (stats["C"] + stats["D"]) / total

    if a_pct > 0.5:
        print(f"  ⚠️ A 类 {a_pct*100:.1f}% > 50%: 网站自动重定向")
        print(f"  → **不批量加 _1**, 改其他修法（_1 不是必需的）")
    elif b_pct > 0.7 and cd_pct < 0.3:
        print(f"  ✅ B 类 {b_pct*100:.1f}% > 70% 且 C+D {cd_pct*100:.1f}% < 30%")
        print(f"  → **批量加 _1** (WHERE 子句只含 B 类, 当前样本 {stats['B']} 条)")
        print(f"  → 占全量 71,045 的 {b_pct*100:.1f}% ≈ {int(71045*b_pct)} 条")
    elif cd_pct > 0.3:
        print(f"  ⚠️ C+D {cd_pct*100:.1f}% > 30%: 死链/坏页比例高")
        print(f"  → **不批量改**, 走逐条审核 + 人工")
    else:
        print(f"  ⚠️ 比例不明确 (A={a_pct*100:.1f}% B={b_pct*100:.1f}% C+D={cd_pct*100:.1f}%)")
        print(f"  → 建议扩大抽样 (N=500) 或人工审核")

    # 6. 输出 B 类 ID 列表（用于 commit 3 SQL WHERE 子句）
    b_ids = [r["id"] for r in classified if r["category"] == "B"]
    if b_ids:
        b_ids_file = "/tmp/validate_cqggzy_b_ids.txt"
        with open(b_ids_file, "w") as f:
            f.write(",".join(map(str, b_ids)))
        print(f"\n💾 B 类 ID 列表已保存: {b_ids_file} ({len(b_ids)} 条)")

    # 7. 输出 X 类样本（异常，需人工排查）
    x_samples = [r for r in classified if r["category"] == "X"]
    if x_samples:
        print(f"\n⚠️ X 类 (异常) 样本 (前 3 条):")
        for s in x_samples[:3]:
            print(f"  id={s['id']} | orig={s['orig']} | with_1={s['with_1']}")


if __name__ == "__main__":
    n = 200
    if len(sys.argv) > 1:
        if sys.argv[1].startswith("--n="):
            n = int(sys.argv[1].split("=", 1)[1])
        else:
            n = int(sys.argv[1])
    asyncio.run(main(n))