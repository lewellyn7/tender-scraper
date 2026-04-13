"""定时采集调度器 - Docker 容器入口

通过 APScheduler 定时触发采集任务，采集结果写入 output/ 目录。
与 Web 服务解耦，独立运行。

运行方式 (docker-compose):
  docker compose run --rm scheduler
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

# 日志配置
logger.add("logs/scheduler.log", rotation="1 day", retention="7 days", level="INFO")


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

    try:
        import asyncio
        from main import run_collection

        result = asyncio.run(run_collection())
        if result:
            logger.info(
                f"[Scheduler] 采集完成: {result.get('filtered', 0)} 条匹配 / "
                f"{result.get('total', 0)} 条总计"
            )
            # 审计日志：采集成功
            try:
                from app.security.audit import write_audit_log, EVENT_CRAWL_COMPLETED
                write_audit_log(
                    EVENT_CRAWL_COMPLETED,
                    user_id=None,
                    ip_address=None,
                    resource="scheduler.daily_collection",
                    result="success",
                    details={
                        "filtered": result.get("filtered", 0),
                        "total": result.get("total", 0),
                        "new_items": result.get("new_items", 0),
                    },
                )
            except Exception as e:
                logger.warning(f"[Scheduler] 审计日志写入失败 (crawl_completed): {e}")
        else:
            logger.warning("[Scheduler] 采集未返回结果")
    except Exception as e:
        logger.error(f"[Scheduler] 采集任务异常: {e}")
        # 审计日志：采集失败
        try:
            from app.security.audit import write_audit_log, EVENT_CRAWL_FAILED
            write_audit_log(
                EVENT_CRAWL_FAILED,
                user_id=None,
                ip_address=None,
                resource="scheduler.daily_collection",
                result="failure",
                details={"error": str(e)},
            )
        except Exception as audit_err:
            logger.warning(f"[Scheduler] 审计日志写入失败 (crawl_failed): {audit_err}")


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
