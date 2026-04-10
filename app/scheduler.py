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
    """定时采集任务"""
    logger.info(f"[Scheduler] 触发采集任务 @ {datetime.now():%Y-%m-%d %H:%M:%S}")
    try:
        # 延迟导入，避免顶层循环依赖
        from main import run_collection
        result = __import__("asyncio").run(run_collection())
        if result:
            logger.info(f"[Scheduler] 采集完成: {result.get('filtered', 0)} 条匹配")
        else:
            logger.warning("[Scheduler] 采集未返回结果")
    except Exception as e:
        logger.error(f"[Scheduler] 采集任务异常: {e}")


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
    logger.info(f"[Scheduler] 下次执行: {scheduler.get_job('daily_collection').next_run_time}")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("[Scheduler] 已停止")


if __name__ == "__main__":
    main()
