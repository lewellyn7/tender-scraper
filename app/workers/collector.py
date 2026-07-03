"""采集 Worker — Redis Pub/Sub 触发器

订阅 redis channel "tender:collect:trigger"，收到触发消息后执行采集。

与 Web 服务完全解耦，独立容器运行。
采集完成后自动发布结果到 "tender:collect:result" channel。

运行方式:
    python -m app.workers.collector

环境变量:
    REDIS_URL       : Redis 连接地址 (默认 redis://localhost:6379/0)
    COLLECT_CHANNEL : 触发 channel 名 (默认 tender:collect:trigger)
    RESULT_CHANNEL  : 结果 channel 名 (默认 tender:collect:result)
"""
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from threading import Thread

import redis

from app.utils.redis_url import parse_redis_url as _parse_redis_url

# ── 日志 ──────────────────────────────────────────────────
import logging
logger = logging.getLogger("collector.worker")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(_h)

# ── 配置 ──────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://:infini_rag_flow@localhost:6379/0")
TRIGGER_CHANNEL = os.getenv("COLLECT_CHANNEL", "tender:collect:trigger")
RESULT_CHANNEL = os.getenv("RESULT_CHANNEL", "tender:collect:result")

# 7-03 失败重试策略 (用户拍板):
# - 最多 3 次尝试 (1 立即 + 2 延时)
# - 延时重试间隔: 60s, 180s (递增)
# - 3 次仍失败 → 主动告警 (TG + audit)
CRAWL_RETRY_MAX = int(os.getenv("CRAWL_RETRY_MAX", "3"))
CRAWL_RETRY_DELAYS = [0, 60, 180]  # 第 1 次立即, 第 2/3 次延时


def _run_collection_sync_with_retry(source: str = "cqggzy") -> dict:
    """7-03 重试包装: 包裹 _run_collection_sync 加重试 + 告警.

    重试策略 (用户拍板 2026-07-03 16:49):
    - 第 1 次: 立即执行
    - 第 2 次: 失败后 60s 重试
    - 第 3 次: 失败后 180s 重试 (递递增 2x backoff)
    - 3 次仍失败: 告警 (Telegram 主, audit 兜底)
    """
    last_error = None
    for attempt in range(1, CRAWL_RETRY_MAX + 1):
        if attempt > 1:
            delay = CRAWL_RETRY_DELAYS[attempt - 1]
            logger.info(
                f"[Collector] 第 {attempt}/{CRAWL_RETRY_MAX} 次重试 "
                f"({source}), 等待 {delay}s..."
            )
            time.sleep(delay)
        else:
            logger.info(f"[Collector] 开始第 {attempt}/{CRAWL_RETRY_MAX} 次尝试 ({source})")

        result = _run_collection_sync(source=source)
        if result.get("ok"):
            if attempt > 1:
                logger.info(
                    f"[Collector] ✅ 重试成功 ({source}) 第 {attempt} 次"
                )
            return result
        last_error = result.get("error", "unknown")

    # 3 次全失败 → 告警
    logger.error(
        f"[Collector] ❌ {CRAWL_RETRY_MAX} 次重试全部失败 ({source}): {last_error}"
    )
    try:
        from app.utils.alerts import send_alert
        send_alert(
            level="critical",
            title=f"采集连续 {CRAWL_RETRY_MAX} 次失败",
            body=(
                f"来源: {source}\n"
                f"最后错误: {last_error}\n"
                f"下次预计重试: 由 scheduler 下一周期 (2h) 触发\n\n"
                f"查日志: docker logs --tail 100 tender-scraper-collector"
            ),
            source=f"collector.{source}",
        )
    except Exception as e:
        logger.error(f"[Collector] 告警发送失败: {e}")
    # 返回带 "exhausted" 标记, 供上层逻辑识别
    return {
        "ok": False,
        "error": last_error,
        "attempts": CRAWL_RETRY_MAX,
        "exhausted": True,
        "source": source,
    }


def _run_collection_sync(source: str = "cqggzy"):
    """同步调用 async run_collection() 或 run_fahcqmu_collection()

    F4 (2026-06-26): 根据 source 路由到不同 pipeline
    - 'cqggzy' / 'scheduler' (默认) → main.run_collection
    - 'fahcqmu'                      → pipeline.run_fahcqmu_collection

    7-03 状态语义修复:
    - ok=True  且 count > 0  → status='ok'
    - ok=True  且 count = 0  → status='degraded' (完成但 0 条, 不算完全 ok)
    - ok=False                → status='failed'
    """
    import asyncio
    try:
        # 延迟导入，避免启动时过早加载
        if source == "fahcqmu":
            from app.core.harvest.pipeline import run_fahcqmu_collection
            logger.info("[Collector] 开始执行 fahcqmu 采集任务")
            t0 = time.time()
            result = asyncio.run(run_fahcqmu_collection())
        else:
            from main import run_collection
            logger.info("[Collector] 开始执行采集任务 (CQGGZY)")
            t0 = time.time()
            result = asyncio.run(run_collection())
        elapsed = time.time() - t0
        if result:
            count = result.get("filtered", 0)
            logger.info(
                f"[Collector] 采集完成 ({source}): {count}/{result.get('total', 0)} "
                f"匹配，耗时 {elapsed:.1f}s"
            )
            return {
                "ok": True,
                "elapsed": round(elapsed, 1),
                "result": result,
                "source": source,
                "count": count,
            }
        else:
            logger.warning(f"[Collector] 采集未返回结果 ({source})")
            return {
                "ok": False,
                "error": "no result (pipeline returned None)",
                "elapsed": round(elapsed, 1),
                "source": source,
            }
    except Exception as e:
        logger.error(f"[Collector] 采集异常 ({source}): {e}")
        logger.exception("[Collector] traceback:")
        return {"ok": False, "error": str(e), "source": source}


def _publish_result(result: dict):
    """发布采集结果到 result channel"""
    try:
        r = redis.Redis(**_parse_redis_url(REDIS_URL))
        r.publish(RESULT_CHANNEL, json.dumps({
            "ts": datetime.now().isoformat(),
            **result
        }, ensure_ascii=False, default=str))
        r.close()
    except Exception as e:
        logger.warning(f"[Collector] 结果发布失败: {e}")


def _query_recent_catnums(minutes: int = 5) -> list:
    """Opt-4: 查询最近 N 分钟新增项目的 catnum 列表 (智能失效用)

    返回 9 位 catnum 集合 (去重), e.g. ["014001001", "014005002"]
    失败返回空 list (调用方走 main 全清兜底)
    """
    try:
        from app.database import get_db
        from datetime import datetime, timedelta
        db = get_db()
        conn = db._get_conn()
        # 最近 N 分钟 scraped_at (采集时间, 不是 publish_date)
        # 使用 projects_cqggzy.created_at (采集入库时间)
        threshold = datetime.now() - timedelta(minutes=minutes)
        placeholder = "%s" if getattr(db, 'USE_PG', False) else "?"
        rows = conn.execute(
            f"SELECT DISTINCT url FROM projects_cqggzy "
            f"WHERE created_at > {placeholder} AND url IS NOT NULL LIMIT 500",
            (threshold,)
        ).fetchall()
        urls = [row[0] if not isinstance(row, dict) else row.get("url", "") for row in rows]
        if urls:
            from app.core.harvest.data_cache import DataCache
            return sorted(DataCache._extract_catnums(urls))
        return []
    except Exception as e:
        logger.warning(f"[Collector] 查询最近 catnum 失败: {e}")
        return []


def _publish_invalidate_smart():
    """Opt-4: 智能失效 - 按 catnum 桶发失效消息, 没有受影响 catnum 时兑底全清 main"""
    try:
        from app.core.harvest.data_cache import DataCache
        affected_catnums = _query_recent_catnums(minutes=5)
        if affected_catnums:
            for c in affected_catnums:
                DataCache.publish_invalidate(f"catnum:{c}")
            logger.info(
                f"[Collector] 已按 catnum 失效 {len(affected_catnums)} 个: "
                f"{affected_catnums[:5]}{'...' if len(affected_catnums) > 5 else ''}"
            )
        else:
            DataCache.publish_invalidate("main")
            logger.info("[Collector] 已发布 DataCache invalidate(main) (兑底)")
    except Exception as e:
        logger.warning(f"[Collector] publish_invalidate 失败: {e}")


class CollectorWorker:
    """Redis Pub/Sub 采集 Worker"""

    def __init__(self):
        self._running = False
        self._thread: Thread = None

    def _listen(self):
        """在独立线程中运行事件循环"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._listen_async())
        loop.close()

    async def _listen_async(self):
        """异步监听 Redis pub/sub（pubsub.listen() 为同步，需用 executor）"""
        loop = asyncio.get_event_loop()
        r = redis.Redis(**_parse_redis_url(REDIS_URL), decode_responses=True)
        pubsub = r.pubsub()
        await loop.run_in_executor(None, lambda: pubsub.subscribe(TRIGGER_CHANNEL))
        logger.info(f"[Collector] 已订阅 channel: {TRIGGER_CHANNEL}")

        try:
            while self._running:
                # listen() 是同步阻塞的，在 executor 中调用
                message = await loop.run_in_executor(None, pubsub.get_message)
                if message is None:
                    await asyncio.sleep(0.1)
                    continue
                if message["type"] not in ("message", "pmessage"):
                    continue
                try:
                    payload = json.loads(message["data"])
                    source = payload.get("source", "cqggzy")
                    logger.info(f"[Collector] 收到触发: source={source}, payload={payload}")
                    # 7-03: 加重试包装 (1 立即 + 2 延时, 3 次都败 → 告警)
                    result = await loop.run_in_executor(
                        None, lambda: _run_collection_sync_with_retry(source=source)
                    )
                    _publish_result(result)
                    # 2026-06-26: PR feat/data-cache-v2 - 通知 web 容器 DataCache 失效
                    # 7-03 调整: 只有成功 (count > 0) 才发 invalidate, 避免 0 采集 们错估缓存
                    if result.get("ok") and result.get("count", 0) > 0:
                        _publish_invalidate_smart()
                    # P1-2: 更新 health state (7-03 状态机 ok/failed/degraded)
                    from app.workers.collector_health import CollectorState
                    if isinstance(result, dict):
                        if not result.get("ok"):
                            status = "failed"
                            count = 0
                            error = result.get("error", "unknown")
                        elif result.get("count", 0) == 0:
                            status = "degraded"  # 完成但 0 条
                            count = 0
                            error = "0 projects collected"
                        else:
                            status = "ok"
                            count = result.get("count", 0)
                            error = None
                        CollectorState.record_crawl(
                            status=status,
                            count=count,
                            error=error,
                            source=source,
                            duration_s=result.get("elapsed"),
                        )
                except json.JSONDecodeError:
                    logger.warning(f"[Collector] 非 JSON 消息: {message['data']}")
        except Exception as e:
            logger.error(f"[Collector] 监听异常: {e}")
        finally:
            try:
                await loop.run_in_executor(None, lambda: pubsub.unsubscribe(TRIGGER_CHANNEL))
                pubsub.close()
                r.close()
            except Exception:
                pass

    def start(self, blocking: bool = True):
        """启动 Worker"""
        logger.info("[Collector] 启动采集 Worker")
        self._running = True
        if blocking:
            self._listen()
        else:
            self._thread = Thread(target=self._listen, daemon=True)
            self._thread.start()

    def stop(self):
        self._running = False
        logger.info("[Collector] 已停止")


# ── 单次触发（供测试和手动调用） ──────────────────────────────

def trigger_collection(blocking: bool = False) -> dict:
    """手动触发一次采集（通过 Redis pub/sub）"""
    try:
        r = redis.Redis(**_parse_redis_url(REDIS_URL))
        msg_id = r.publish(TRIGGER_CHANNEL, json.dumps({
            "source": "manual",
            "triggered_at": datetime.now().isoformat(),
        }))
        r.close()
        logger.info(f"[Collector] 已发送触发消息，接收者: {msg_id}")
        if blocking:
            return _run_collection_sync()
        return {"ok": True, "subscribers": msg_id}
    except Exception as e:
        logger.error(f"[Collector] 触发失败: {e}")
        return {"ok": False, "error": str(e)}


# ── 入口 ──────────────────────────────────────────────────

def main():
    import signal
    from app.workers.collector_health import start_health_server, stop_health_server

    worker = CollectorWorker()

    def signal_handler(sig, frame):
        logger.info(f"[Collector] 收到信号 {sig}，停止中...")
        worker.stop()
        stop_health_server()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # P1-2: 启动 health server (端口 8001) — docker healthcheck 探针
    health_port = int(os.getenv("COLLECTOR_HEALTH_PORT", "8001"))
    start_health_server(host="0.0.0.0", port=health_port)

    worker.start(blocking=True)


if __name__ == "__main__":
    main()
