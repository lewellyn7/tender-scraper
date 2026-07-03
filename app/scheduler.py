"""定时采集调度器 - Docker 容器入口

通过 APScheduler 定时触发采集任务，通过 Redis Pub/Sub 发布采集指令。
与实际采集逻辑完全解耦。

采集 Worker（app.workers.collector）订阅 redis channel 响应触发。

运行方式 (docker-compose):
  docker compose run --rm scheduler

7-03 watchdog 增强 (用户拍板 2026-07-03 16:49):
- 启动自检: 检查上次周期结果, 失败则补发 + 告警
- watchdog 巡检: 每 5 分钟检 collector 状态, 超 2.5h 未成功 → 告警
- 20:00 日报: 今日 cron 触发/成功/失败/新增项目数
- collector 死了 → 告警
- collector 失败 3 次 → 主动告警 (collector 自己发, watchdog 也会发, 重复告警去重)
"""
import json
import os
import sys
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.utils.redis_url import parse_redis_url as _parse_redis_url


# ── 配置 ──────────────────────────────────────────────────

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger
import redis

# 日志配置
logger.add("/dev/stderr", format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}", level="INFO", colorize=False)

# ── Redis 配置 ──────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://:infini_rag_flow@localhost:6379/0")
TRIGGER_CHANNEL = os.getenv("COLLECT_CHANNEL", "tender:collect:trigger")
RESULT_CHANNEL = os.getenv("RESULT_CHANNEL", "tender:collect:result")

# 7-03 watchdog 配置
WATCHDOG_STALE_SECONDS = int(os.getenv("WATCHDOG_STALE_SECONDS", "9000"))  # 2.5h 默认
WATCHDOG_CHECK_INTERVAL = int(os.getenv("WATCHDOG_CHECK_INTERVAL", "300"))  # 5min 默认
COLLECTOR_HEALTH_URL = os.getenv(
    "COLLECTOR_HEALTH_URL",
    "http://tender-scraper-collector:8001/health/collector-state",
)

# 7-03 日报: 今日采集统计 (scheduler 模块级, watchdog 累加)
_DAILY_STATS = {
    "date": "",  # YYYY-MM-DD
    "cron_triggered": 0,  # 今日 cron 触发次数
    "last_result": None,  # {"ok": bool, "error": str, "elapsed": float}
    "started_at": None,  # 今日首次启动时间
}


class _HealthHandler(BaseHTTPRequestHandler):
    """HTTP health endpoint handler."""
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        elif self.path == "/health/collector-state":
            # 7-03: 转发 collector 状态, 便于跨容器 debug
            try:
                with urllib.request.urlopen(COLLECTOR_HEALTH_URL, timeout=3) as resp:
                    body = resp.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body)
            except Exception as e:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, format, *args):
        pass  # suppress logging


def _start_health_server(port: int = 8000):
    """Start lightweight HTTP health server in a daemon thread."""
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    logger.info(f"[HealthServer] listening on 0.0.0.0:{port}/health")


# ── 采集触发 ──────────────────────────────────────────────
def _publish_trigger() -> bool:
    """发布采集触发消息到 Redis channel，返回是否成功"""
    try:
        r = redis.Redis(**_parse_redis_url(REDIS_URL))
        msg_id = r.publish(TRIGGER_CHANNEL, json.dumps({
            "source": "scheduler",
            "triggered_at": datetime.now().isoformat(),
        }, ensure_ascii=False))
        r.close()
        logger.info(f"[Scheduler] 已发送采集触发 (接收者: {msg_id})")
        return msg_id > 0
    except Exception as e:
        logger.error(f"[Scheduler] Redis 触发发布失败: {e}")
        return False


def _publish_fahcqmu_trigger() -> bool:
    """发布重医附一院采集触发消息到 Redis channel（F4: 2026-06-26）。

    与 CQGGZY 共用 TRIGGER_CHANNEL，但 payload 中带 source='fahcqmu'
    Collector Worker 端根据 source 字段决定调用哪个 pipeline (run_collection vs run_fahcqmu_collection)。
    """
    try:
        r = redis.Redis(**_parse_redis_url(REDIS_URL))
        msg_id = r.publish(TRIGGER_CHANNEL, json.dumps({
            "source": "fahcqmu",
            "triggered_at": datetime.now().isoformat(),
        }, ensure_ascii=False))
        r.close()
        logger.info(f"[Scheduler] 已发送 fahcqmu 采集触发 (接收者: {msg_id})")
        return msg_id > 0
    except Exception as e:
        logger.error(f"[Scheduler] fahcqmu Redis 触发发布失败: {e}")
        return False


def job_run_collection():
    """定时采集任务（调度器触发入口）"""
    global _DAILY_STATS
    logger.info(f"[Scheduler] 触发采集任务 @ {datetime.now():%Y-%m-%d %H:%M:%S}")

    # 7-03 累加今日 cron 触发次数
    today = datetime.now().strftime("%Y-%m-%d")
    if _DAILY_STATS["date"] != today:
        _DAILY_STATS = {
            "date": today,
            "cron_triggered": 0,
            "last_result": None,
            "started_at": datetime.now().isoformat(),
        }
    _DAILY_STATS["cron_triggered"] += 1

    # 审计日志：采集开始
    try:
        from app.security.audit import write_audit_log, EVENT_CRAWL_STARTED
        write_audit_log(
            EVENT_CRAWL_STARTED,
            user_id=None,
            ip_address=None,
            resource="scheduler.daily_collection",
            result="started",
            details={"triggered_at": datetime.now().isoformat()},
        )
    except Exception as e:
        logger.warning(f"[Scheduler] 审计日志写入失败 (crawl_started): {e}")

    # 发布 Redis 消息，由 Collector Worker 执行实际采集
    ok = _publish_trigger()
    if not ok:
        logger.error("[Scheduler] 采集触发发布失败，Worker 可能未订阅")
        try:
            from app.utils.alerts import send_alert
            send_alert(
                level="error",
                title="采集触发发布失败",
                body="Redis publish 失败, collector 收不到消息.\n可能原因: Redis 不可达 / 凭证错",
                source="scheduler",
            )
        except Exception as e:
            logger.warning(f"[Scheduler] 告警发送失败: {e}")
        try:
            from app.security.audit import write_audit_log, EVENT_CRAWL_FAILED
            write_audit_log(
                EVENT_CRAWL_FAILED,
                user_id=None,
                ip_address=None,
                resource="scheduler.daily_collection",
                result="failure",
                details={"error": "Redis publish failed"},
            )
        except Exception:
            pass


# ── 7-03 watchdog 实现 ────────────────────────────────────
_last_watchdog_alert_at: float = 0
WATCHDOG_ALERT_COOLDOWN = 1800  # 同一类告警 30min 冷却 (避免刷屏)


def _fetch_collector_state() -> dict | None:
    """拉取 collector 容器 health 状态 (urllib 同步, 3s 超时).

    返回: {status, last_crawl_at, last_crawl_age_s, last_crawl_status, ...} 或 None (拉取失败)
    """
    try:
        with urllib.request.urlopen(COLLECTOR_HEALTH_URL, timeout=3) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        logger.debug(f"[Watchdog] collector 状态拉取失败: {e}")
    except Exception as e:
        logger.warning(f"[Watchdog] collector 状态拉取异常: {e}")
    return None


def job_watchdog_check():
    """watchdog 巡检 (每 5min): 检查 collector 健康 + stale 检测.

    检测项:
    1. collector 容器死了 (HTTP 拉不到) → critical 告警
    2. last_crawl_age > WATCHDOG_STALE_SECONDS (默认 2.5h) → error 告警
    3. collector 状态 degraded (连续失败 ≥ 3) → warning 告警
    4. consecutive_failures > 0 但 < 3 → info 日志 (不告警)

    告警去重: 同类告警 30min 冷却 (避免告警刷屏)
    """
    global _last_watchdog_alert_at

    state = _fetch_collector_state()
    if state is None:
        # 拉不到 → collector 死了
        if time.time() - _last_watchdog_alert_at < WATCHDOG_ALERT_COOLDOWN:
            return
        try:
            from app.utils.alerts import send_alert
            send_alert(
                level="critical",
                title="Collector 容器失联",
                body=(
                    f"无法访问 {COLLECTOR_HEALTH_URL}\n"
                    f"容器可能已挂/网络断开/凭证失效\n"
                    f"建议: docker ps | grep collector; docker logs --tail 50 tender-scraper-collector"
                ),
                source="watchdog",
            )
            _last_watchdog_alert_at = time.time()
        except Exception as e:
            logger.warning(f"[Watchdog] 告警发送失败: {e}")
        return

    # 检查 stale
    age = state.get("last_crawl_age_s")
    if age is not None and age > WATCHDOG_STALE_SECONDS:
        if time.time() - _last_watchdog_alert_at < WATCHDOG_ALERT_COOLDOWN:
            return
        try:
            from app.utils.alerts import send_alert
            send_alert(
                level="error",
                title=f"采集停滞 {round(age/3600, 1)}h",
                body=(
                    f"距上次成功采集已 {round(age/60, 0)} 分钟\n"
                    f"阈值: {WATCHDOG_STALE_SECONDS/3600}h ({WATCHDOG_STALE_SECONDS}s)\n"
                    f"collector 状态: {state.get('status')}\n"
                    f"上次状态: {state.get('last_crawl_status')}\n"
                    f"上次 count: {state.get('last_crawl_count')}\n"
                    f"连续失败: {state.get('consecutive_failures')}\n\n"
                    f"人工触发: docker exec tender-scraper-scheduler python -m app.scheduler --trigger-now"
                ),
                source="watchdog",
            )
            _last_watchdog_alert_at = time.time()
        except Exception as e:
            logger.warning(f"[Watchdog] 告警发送失败: {e}")
        return

    # 检查 degraded
    if state.get("status") == "degraded":
        if time.time() - _last_watchdog_alert_at < WATCHDOG_ALERT_COOLDOWN:
            return
        try:
            from app.utils.alerts import send_alert
            send_alert(
                level="warning",
                title="Collector 连续失败",
                body=(
                    f"连续失败 {state.get('consecutive_failures')} 次 (≥3 触发 degraded)\n"
                    f"最后一次错误: {state.get('last_error', 'unknown')}\n"
                    f"今日总失败/总采集: {state.get('total_fail')}/{state.get('total_crawls')}\n\n"
                    f"collector 端已加重试 3 次策略 + 主动告警, 此为 watchdog 二重告警"
                ),
                source="watchdog",
            )
            _last_watchdog_alert_at = time.time()
        except Exception as e:
            logger.warning(f"[Watchdog] 告警发送失败: {e}")
        return

    # 一切正常
    logger.debug(
        f"[Watchdog] ✅ collector 健康 "
        f"(age={age}s, status={state.get('last_crawl_status')}, "
        f"failures={state.get('consecutive_failures')})"
    )


def job_daily_report():
    """20:00 日报 (用户拍板 2026-07-03 16:49).

    内容:
    - 今日 cron 触发次数
    - collector 今日总成功/总失败 (从 collector 状态取)
    - 今日新增项目数 (从 DB 查)
    - 健康总结
    """
    logger.info("[Scheduler] 发送 20:00 日报")
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        # 1) 今日新增项目数 (从 DB)
        new_projects_today = 0
        try:
            import psycopg2
            db_url = os.environ.get(
                "DATABASE_URL",
                "postgresql://root:infini_rag_flow@postgres:5432/tender_scraper",
            )
            conn = psycopg2.connect(db_url)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM projects_cqggzy WHERE scraped_at::date = %s",
                    (today,),
                )
                new_projects_today = cur.fetchone()[0]
            conn.close()
        except Exception as e:
            logger.warning(f"[Scheduler] 日报: DB 查新增失败: {e}")

        # 2) collector 今日累计
        state = _fetch_collector_state() or {}
        total_ok = state.get("total_ok", "?")
        total_fail = state.get("total_fail", "?")
        consecutive_fail = state.get("consecutive_failures", 0)
        last_status = state.get("last_crawl_status", "unknown")
        last_count = state.get("last_crawl_count", "?")

        # 3) 拼消息
        cron_count = _DAILY_STATS.get("cron_triggered", 0)
        health_label = {
            "ok": "✅ 健康",
            "degraded": "⚠️ 降级",
            "idle": "⏸️ 空闲",
            "failed": "❌ 失败",
        }.get(state.get("status", "?"), state.get("status", "?"))

        body = (
            f"🗓️ 日期: {today}\n"
            f"📅 Cron 触发: {cron_count} 次 (CQGGZY 2h 一次, 应 6-7 次)\n"
            f"✅ 成功: {total_ok} / ❌ 失败: {total_fail}\n"
            f"📦 今日新增: {new_projects_today} 条\n"
            f"🔋 健康: {health_label}\n"
            f"📊 最后采集: {last_status} (count={last_count})\n"
            f"⏱️ 连续失败: {consecutive_fail}\n"
        )

        from app.utils.alerts import send_alert
        send_alert(
            level="info",
            title="📊 采集日报",
            body=body,
            source="scheduler.daily_report",
        )
    except Exception as e:
        logger.error(f"[Scheduler] 日报发送失败: {e}")


def job_startup_self_check():
    """启动自检: scheduler 启动时, 拉 collector 上次结果.

    - 如果上次失败 → 立即补发 1 次 (用户拍板: 立即重试)
    - 如果 collector 死了 → 告警
    - 如果上次 stale > 2.5h → 告警
    """
    logger.info("[Scheduler] 启动自检中...")
    state = _fetch_collector_state()
    if state is None:
        logger.warning("[Scheduler] 启动自检: collector 失联, 发告警")
        try:
            from app.utils.alerts import send_alert
            send_alert(
                level="critical",
                title="Scheduler 启动时 Collector 失联",
                body=(
                    f"无法访问 {COLLECTOR_HEALTH_URL}\n"
                    f"scheduler 已启动但 collector 不在, 采集不会执行\n"
                    f"建议: docker start tender-scraper-collector"
                ),
                source="scheduler.startup",
            )
        except Exception as e:
            logger.warning(f"[Scheduler] 启动自检告警失败: {e}")
        return

    last_status = state.get("last_crawl_status")
    last_count = state.get("last_crawl_count", 0)
    age = state.get("last_crawl_age_s")

    logger.info(
        f"[Scheduler] 启动自检: 上次状态={last_status}, "
        f"count={last_count}, age={age}s"
    )

    # 失败 → 补发
    if last_status in ("failed", "degraded") or (last_status == "ok" and last_count == 0):
        logger.warning(
            f"[Scheduler] 启动自检: 上次未成功 ({last_status}, count={last_count}), "
            f"补发 1 次"
        )
        try:
            from app.utils.alerts import send_alert
            send_alert(
                level="warning",
                title="启动自检: 上次未成功, 补发",
                body=(
                    f"scheduler 启动时发现上次采集未成功\n"
                    f"上次状态: {last_status}\n"
                    f"上次 count: {last_count}\n"
                    f"距上次: {round(age/60, 0) if age else '?'} 分钟\n"
                    f"已自动补发 1 次"
                ),
                source="scheduler.startup",
            )
        except Exception as e:
            logger.warning(f"[Scheduler] 启动自检告警失败: {e}")
        _publish_trigger()
        return

    # stale
    if age and age > WATCHDOG_STALE_SECONDS:
        logger.warning(
            f"[Scheduler] 启动自检: 已 {round(age/3600, 1)}h 未成功, 补发 + 告警"
        )
        try:
            from app.utils.alerts import send_alert
            send_alert(
                level="error",
                title="启动自检: 长时间未采集",
                body=(
                    f"距上次成功采集 {round(age/3600, 1)}h, "
                    f"阈值 {WATCHDOG_STALE_SECONDS/3600}h\n"
                    f"已自动补发 1 次"
                ),
                source="scheduler.startup",
            )
        except Exception as e:
            logger.warning(f"[Scheduler] 启动自检告警失败: {e}")
        _publish_trigger()
        return

    logger.info("[Scheduler] 启动自检: ✅ 一切正常")


# ── 入口 ──────────────────────────────────────────────────
def main():
    _start_health_server(port=int(os.getenv("PORT", 8000)))
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")

    # 每 2 小时执行一次（08:00 / 10:00 / 12:00 / 14:00 / 16:00 / 18:00 / 20:00）
    scheduler.add_job(
        job_run_collection,
        CronTrigger(minute="0", hour="8,10,12,14,16,18,20", timezone="Asia/Shanghai"),
        id="daily_collection",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # F4: 重医附一院每日 21:00 单独跑 (错开 CQGGZY 周期，避免同时打满 worker)
    scheduler.add_job(
        _publish_fahcqmu_trigger,
        CronTrigger(minute="0", hour="21", timezone="Asia/Shanghai"),
        id="fahcqmu_daily",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # 7-03: watchdog 巡检 (每 5min)
    scheduler.add_job(
        job_watchdog_check,
        IntervalTrigger(seconds=WATCHDOG_CHECK_INTERVAL, timezone="Asia/Shanghai"),
        id="watchdog_check",
        replace_existing=True,
        next_run_time=datetime.now() + timedelta(seconds=10),  # 启动后 10s 首次跑
    )

    # 7-03: 20:00 日报
    scheduler.add_job(
        job_daily_report,
        CronTrigger(minute="0", hour="20", timezone="Asia/Shanghai"),
        id="daily_report",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    logger.info("[Scheduler] 定时采集调度器已启动")
    logger.info("  - CQGGZY  每 2 小时一次: 08/10/12/14/16/18/20:00")
    logger.info("  - fahcqmu 每日 21:00")
    logger.info(f"  - watchdog  每 {WATCHDOG_CHECK_INTERVAL}s (stale={WATCHDOG_STALE_SECONDS}s)")
    logger.info("  - 日报   每日 20:00")

    job = scheduler.get_job("daily_collection")
    if job:
        next_time = getattr(job, "next_run_time", None)
        logger.info(f"[Scheduler] 下次 CQGGZY 执行: {next_time}")
    else:
        logger.info("[Scheduler] 下次 CQGGZY 执行: 未找到 daily_collection job")

    fahc_job = scheduler.get_job("fahcqmu_daily")
    if fahc_job:
        next_time = getattr(fahc_job, "next_run_time", None)
        logger.info(f"[Scheduler] 下次 fahcqmu 执行: {next_time}")

    # 7-03: 启动自检 (同步执行, 不阻塞 scheduler.start())
    threading.Thread(target=job_startup_self_check, daemon=True).start()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("[Scheduler] 已停止")


if __name__ == "__main__":
    main()
