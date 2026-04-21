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
from datetime import datetime

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
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")

    # 默认：每天 08:00 / 12:00 / 18:00 执行
    scheduler.add_job(
        job_run_collection,
        CronTrigger(hour="08,12,18", minute="0"),
        id="daily_collection",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    logger.info("[Scheduler] 定时采集调度器已启动 (08:00 / 12:00 / 18:00)")

    job = scheduler.get_job("daily_collection")
    if job:
        next_time = getattr(job, "next_run_time", None)
        logger.info(f"[Scheduler] 下次执行: {next_time}")
    else:
        logger.info("[Scheduler] 下次执行: 未找到 daily_collection job")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("[Scheduler] 已停止")


if __name__ == "__main__":
    main()
