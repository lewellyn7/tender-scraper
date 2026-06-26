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


def _parse_redis_url(url: str) -> dict:
    """解析 redis:// URL 为 redis-py 连接参数"""
    import re
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


def _run_collection_sync(source: str = "cqggzy"):
    """同步调用 async run_collection() 或 run_fahcqmu_collection()

    F4 (2026-06-26): 根据 source 路由到不同 pipeline
    - 'cqggzy' / 'scheduler' (默认) → main.run_collection
    - 'fahcqmu'                      → pipeline.run_fahcqmu_collection
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
            logger.info(
                f"[Collector] 采集完成 ({source}): {result.get('filtered', 0)}/{result.get('total', 0)} "
                f"匹配，耗时 {elapsed:.1f}s"
            )
            return {"ok": True, "elapsed": round(elapsed, 1), "result": result, "source": source}
        else:
            logger.warning(f"[Collector] 采集未返回结果 ({source})")
            return {"ok": False, "error": "no result", "elapsed": round(elapsed, 1), "source": source}
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
                    result = await loop.run_in_executor(None, lambda: _run_collection_sync(source=source))
                    _publish_result(result)
                    # 2026-06-26: PR feat/data-cache-v2 - 通知 web 容器 DataCache 失效
                    try:
                        from app.core.harvest.data_cache import DataCache
                        DataCache.publish_invalidate("main")
                        logger.info(f"[Collector] 已发布 DataCache invalidate(main)")
                    except Exception as e:
                        logger.warning(f"[Collector] publish_invalidate 失败: {e}")
                    # P1-2: 更新 health state
                    from app.workers.collector_health import CollectorState
                    status = result.get("status", "ok") if isinstance(result, dict) else "ok"
                    count = result.get("total", 0) if isinstance(result, dict) else 0
                    CollectorState.record_crawl(status, count=count)
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
