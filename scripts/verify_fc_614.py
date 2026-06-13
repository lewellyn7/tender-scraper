#!/usr/bin/env python3
"""
6-14 fc 完整率验证脚本（v2: 智能阈值）
- 对比 6-14 采集周期前后的 full_content 完整率
- 区分 采集失败 (< 30 字符) vs 合法短 (30-200 字符 "详见附件" 模板)
- 只对 采集失败 告警，合法短 只做参考
"""
import asyncio
import sys
from datetime import datetime, date, timedelta
import psycopg2
import os

# 容器内走 postgres hostname; 容器外走 localhost:5435 (host port mapping)
PG_DSN = os.environ.get("PG_DSN") or (
    "postgresql://root:root123@postgres:5432/tender_scraper"
    if os.path.exists("/app") else
    "postgresql://root:root123@localhost:5435/tender_scraper"
)

TELEGRAM_BOT_TOKEN = None  # 如有 bot token 填这里
TELEGRAM_CHAT_ID = None    # 如有 chat_id 填这里

# 智能阈值（基于 6-14 04:50 审核发现）
FAIL_THRESHOLD = 30       # < 30 字符 = 采集失败/SPA 未渲染
LEGITIMATE_THRESHOLD = 200  # < 200 但 >= 30 = 合法短（详见附件、答疑补遗）
ALERT_FAIL_PCT = 0.5      # 采集失败占比 > 0.5% 告警


async def verify(target_date: str = None):
    if target_date is None:
        target_date = date.today().strftime("%Y-%m-%d")

    target_date_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
    next_date = (target_date_obj + timedelta(days=1)).strftime("%Y-%m-%d")

    conn = psycopg2.connect(PG_DSN)
    cur = conn.cursor()

    # 1. 6-14 抓取周期内的 fc 分布（智能分桶）
    cur.execute("""
        SELECT
            COUNT(*) FILTER (WHERE LENGTH(full_content) >= %(th_legit)s) AS has_fc,
            COUNT(*) FILTER (WHERE LENGTH(full_content) >= %(th_fail)s AND LENGTH(full_content) < %(th_legit)s) AS legitimate_short,
            COUNT(*) FILTER (WHERE LENGTH(full_content) > 0 AND LENGTH(full_content) < %(th_fail)s) AS likely_fail,
            COUNT(*) FILTER (WHERE full_content IS NULL OR full_content = '') AS empty,
            COUNT(*) AS total
        FROM projects_cqggzy
        WHERE scraped_at >= %(start)s::timestamp
          AND scraped_at < %(end)s::timestamp
          AND url NOT LIKE '%%/tenderplan/%%'
    """, {
        "th_legit": LEGITIMATE_THRESHOLD,
        "th_fail": FAIL_THRESHOLD,
        "start": target_date,
        "end": next_date,
    })
    has_fc, legit_short, likely_fail, empty, total = cur.fetchone()

    pct_has = (has_fc * 100.0 / total) if total > 0 else 0
    pct_legit = (legit_short * 100.0 / total) if total > 0 else 0
    pct_fail = ((likely_fail + empty) * 100.0 / total) if total > 0 else 0

    print(f"\n{'='*70}")
    print(f"📊 {target_date} 采集周期 fc 完整率验证 (v2 智能阈值)")
    print(f"{'='*70}")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"范围: scraped_at BETWEEN {target_date} 00:00 AND {next_date} 00:00")
    print(f"---")
    print(f"总记录:           {total:>5}")
    print(f"✅ 有 fc (>=200): {has_fc:>5} ({pct_has:.1f}%)")
    print(f"📎 合法短 (30-200): {legit_short:>3} ({pct_legit:.2f}%)  [详见附件 / 答疑补遗 / 终止公告]")
    print(f"🚨 采集失败 (<30):  {likely_fail:>3} ({pct_fail:.2f}%)")
    print(f"❌ empty:           {empty:>5}")
    print(f"{'='*70}")

    # 2. 列出 likely_fail 样本（采集失败的，全列）
    if likely_fail > 0:
        cur.execute("""
            SELECT id, title, LENGTH(full_content) AS fc_len, url
            FROM projects_cqggzy
            WHERE scraped_at >= %(start)s::timestamp
              AND scraped_at < %(end)s::timestamp
              AND LENGTH(full_content) > 0 AND LENGTH(full_content) < %(th_fail)s
              AND url NOT LIKE '%%/tenderplan/%%'
            ORDER BY scraped_at DESC
            LIMIT 20
        """, {"start": target_date, "end": next_date, "th_fail": FAIL_THRESHOLD})
        samples = cur.fetchall()
        print(f"\n🚨 采集失败样本 (前 20):")
        for sid, title, fc_len, url in samples:
            print(f"  [{sid}] {fc_len} 字符 | {title[:60]} | {url[:60]}")

    # 3. 历史 90 天对照（baseline）
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
    print(f"\n📈 历史 90 天基线对照: {h90_has}/{h90_total} = {h90_pct:.1f}%")

    # 4. 判定
    if total == 0:
        print(f"\n⏳ {target_date} 采集周期未到 (total=0), 跳过判定")
        conn.close()
        return 0

    # 新逻辑：只对 采集失败 告警
    fail_count = likely_fail + empty
    fail_pct = (fail_count * 100.0 / total) if total > 0 else 0
    fail_ok = fail_pct <= ALERT_FAIL_PCT
    legit_ok = pct_has >= 99.0  # 主目标还是 99% 完整

    print(f"\n{'='*70}")
    print(f"判定标准:")
    print(f"  采集失败占比:  {fail_pct:.2f}% 阈值 ≤ {ALERT_FAIL_PCT}%  →  {'✅' if fail_ok else '🚨 FAIL'}")
    print(f"  整体完整率:    {pct_has:.1f}% 阈值 ≥ 99.0%        →  {'✅' if legit_ok else '⚠️ DEGRADED'}")
    print(f"  合法短占比:    {pct_legit:.2f}% 仅供参考         →  📎 {legit_short} 条")
    print(f"{'='*70}")

    if not fail_ok:
        print(f"\n🚨 采集失败 {fail_count} 条 ({fail_pct:.2f}%) 超过阈值 {ALERT_FAIL_PCT}%！")
        print(f"   建议: 检查采集器日志 + curl 验证样本 URL")
        print(f"   如确认是 SPA 渲染问题: 考虑 headless 浏览器 (playwright)")

    conn.close()

    # 5. 发送 Telegram
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID and not fail_ok:
        try:
            import requests
            msg = (
                f"🚨 {target_date} fc 采集失败告警\n"
                f"失败: {fail_count} 条 ({fail_pct:.2f}%, 阈值 {ALERT_FAIL_PCT}%)\n"
                f"完整率: {pct_has:.1f}%\n"
                f"合法短: {legit_short} 条 ({pct_legit:.2f}%)"
            )
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}
            )
        except Exception as e:
            print(f"Telegram 发送失败: {e}")

    return 0 if (fail_ok and legit_ok) else 1


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(asyncio.run(verify(target)))
