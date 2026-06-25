"""定时采集调度器 - Docker 容器入口

通过 APScheduler 定时触发采集任务，通过 Redis Pub/Sub 发布采集指令。
与实际采集逻辑完全解耦。

采集 Worker（app.workers.collector）订阅 redis channel 响应触发。

运行方式 (docker-compose):
  docker compose run --rm scheduler
"""
import json
import os
import re
import sys
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
import redis

# 日志配置
logger.add("/dev/stderr", format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}", level="INFO", colorize=False)

# ── Redis 配置 ──────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://:infini_rag_flow@localhost:6379/0")
TRIGGER_CHANNEL = os.getenv("COLLECT_CHANNEL", "tender:collect:trigger")


def _parse_redis_url(url: str) -> dict:
    m = re.match(r"redis://(?::([^@]+)@)?([^:]+):(\d+)(?:/(\d+))?", url)
    if not m:
        return {"host": "localhost", "port": 6379, "db": 0, "password": None}
    password, host, port, db = m.groups()
    return {
        "host": host,
        "port": int(port),
        "db": int(db) if db else 0,
        "password": password,
    }


class _HealthHandler(BaseHTTPRequestHandler):
    """HTTP health endpoint handler."""
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
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
    logger.info(f"[Scheduler] 触发采集任务 @ {datetime.now():%Y-%m-%d %H:%M:%S}")

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

    logger.info("[Scheduler] 定时采集调度器已启动")
    logger.info("  - CQGGZY  每 2 小时一次: 08/10/12/14/16/18/20:00")
    logger.info("  - fahcqmu 每日 21:00")

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

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("[Scheduler] 已停止")


if __name__ == "__main__":
    main()
