#!/usr/bin/env python3
"""
6-14 fc 完整率验证脚本
- 对比 6-14 采集周期前后的 full_content 完整率
- 检查 6-14 0:00~23:59 抓取的新记录有没有 tiny_fc (应该接近 0)
- 如果 < 99%, 立即 Telegram 告警
"""
import asyncio
import sys
from datetime import datetime, date, timedelta
import psycopg2
import os

# 容器内走 postgres hostname; 容器外走 localhost
PG_DSN = os.environ.get(
    "PG_DSN",
    "postgresql://root:root123@postgres:5432/tender_scraper"
    if os.path.exists("/app") else
    "postgresql://root:root123@localhost:5432/tender_scraper"
)

TELEGRAM_BOT_TOKEN = None  # 如有 bot token 填这里
TELEGRAM_CHAT_ID = None    # 如有 chat_id 填这里

async def verify():
    conn = psycopg2.connect(PG_DSN)
    cur = conn.cursor()

    # 1. 6-14 抓取周期内的 fc 完整率
    cur.execute("""
        SELECT
            COUNT(*) FILTER (WHERE LENGTH(full_content) >= 200) AS has_fc,
            COUNT(*) FILTER (WHERE LENGTH(full_content) < 200 AND full_content IS NOT NULL AND full_content != '') AS tiny,
            COUNT(*) FILTER (WHERE full_content IS NULL OR full_content = '') AS empty,
            COUNT(*) AS total
        FROM projects_cqggzy
        WHERE scraped_at >= '2026-06-14 00:00:00'::timestamp
          AND scraped_at < '2026-06-15 00:00:00'::timestamp
          AND url NOT LIKE '%/tenderplan/%'
    """)
    has_fc, tiny, empty, total = cur.fetchone()
    pct = (has_fc * 100.0 / total) if total > 0 else 0

    print(f"\n{'='*60}")
    print(f"📊 6-14 采集周期 fc 完整率验证")
    print(f"{'='*60}")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"范围: scraped_at BETWEEN 6-14 00:00 AND 6-15 00:00")
    print(f"---")
    print(f"总记录:     {total:>5}")
    print(f"有 fc:      {has_fc:>5} ({pct:.1f}%)")
    print(f"tiny fc:    {tiny:>5} ({tiny*100/total if total else 0:.2f}%)")
    print(f"empty:      {empty:>5} ({empty*100/total if total else 0:.2f}%)")
    print(f"{'='*60}")

    # 2. 列出 tiny fc 样本 (前 10 条)
    if tiny > 0:
        cur.execute("""
            SELECT id, title, LENGTH(full_content) AS fc_len, url
            FROM projects_cqggzy
            WHERE scraped_at >= '2026-06-14 00:00:00'::timestamp
              AND scraped_at < '2026-06-15 00:00:00'::timestamp
              AND LENGTH(full_content) < 200
              AND full_content IS NOT NULL AND full_content != ''
              AND url NOT LIKE '%/tenderplan/%'
            ORDER BY scraped_at DESC
            LIMIT 10
        """)
        samples = cur.fetchall()
        print(f"\n⚠️  tiny fc 样本 (前 10):")
        for sid, title, fc_len, url in samples:
            print(f"  [{sid}] {fc_len} 字符 | {title[:60]} | {url[:60]}")
    
    # 3. 历史 90 天对照
    cur.execute("""
        SELECT
            COUNT(*) FILTER (WHERE LENGTH(full_content) >= 200) AS has_fc,
            COUNT(*) AS total
        FROM projects_cqggzy
        WHERE publish_date >= CURRENT_DATE - INTERVAL '90 days'
          AND url NOT LIKE '%/tenderplan/%'
    """)
    h90_has, h90_total = cur.fetchone()
    h90_pct = (h90_has * 100.0 / h90_total) if h90_total > 0 else 0
    print(f"\n📈 历史 90 天对照: {h90_has}/{h90_total} = {h90_pct:.1f}%")
    
    # 4. 判定 (total=0 表示 6-14 还没到, 跳过)
    if total == 0:
        print(f"\n⏳ 6-14 采集周期未到 (total=0), 跳过判定")
        conn.close()
        return 0
    ok = pct >= 99.0
    print(f"\n{'✅' if ok else '❌'} 判定: 6-14 完整率 {pct:.1f}% {'≥' if ok else '<'} 99%")
    
    if not ok:
        print(f"\n🚨 6-14 完整率 {pct:.1f}% 低于 99% 阈值！")
        print(f"   tiny fc: {tiny}, empty: {empty}")
        print(f"   建议: 检查 /tmp/backfill_app_detail.log + 跑下一次采集前 5 条记录 curl 验证")

    conn.close()
    
    # 5. 发送 Telegram (可选)
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID and not ok:
        try:
            import requests
            msg = f"🚨 6-14 fc 完整率 {pct:.1f}% < 99%\ntiny: {tiny}, empty: {empty}, total: {total}"
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}
            )
        except Exception as e:
            print(f"Telegram 发送失败: {e}")
    
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(verify()))
