#!/usr/bin/env python3
"""
DataCache v2 - 统一数据缓存层 (服务所有 read 端点)

2026-06-26 重新设计 (PR feat/data-cache-v2)

## 架构 (3 层 + 2 类失效 + 1 个预热)
- L1: in-process dict (线程安全, asyncio-safe)
- L2: Redis gzip (跨重启, 跨 worker)
- L3: PostgreSQL (源)
- 失效: TTL + Redis Pub/Sub (采集完发 publish → web 订阅 → invalidate)
- 预热: web 容器启动 30s 后异步 warm_up()

## 设计目标
- 冷启动 < 50ms (L1 预热完成)
- 热缓存 < 10ms (L1 hit)
- Filter 响应级 cache (5min TTL) < 3ms
- 采集完 30s 内自动失效 (Pub/Sub)
- 7 端点统一接入 (1 次 DB 查询/预热周期)

## 不做的事 (与 v1 PR #47 对比)
- ✅ Pub/Sub 实时失效 (v1 缺)
- ✅ Filter 响应级 cache (v1 缺)
- ✅ L2 异步写入 (v1 同步阻塞)
- ✅ 多端点接入 (v1 只服务 Data 页)
- ✅ 启动预热 (v1 缺)
"""

import asyncio
import gzip
import json
# import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

# ━━━ 配置 ━━━
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_KEY_MAIN = "projects:cache:full:v2"
REDIS_PUBSUB_CHANNEL = "data:cache:invalidate"

IN_PROCESS_TTL_MAIN = int(os.getenv("DATA_CACHE_L1_TTL", "3600"))        # 1h
IN_PROCESS_TTL_FILTER = int(os.getenv("DATA_CACHE_L1_FILTER_TTL", "300")) # 5min
REDIS_TTL = int(os.getenv("DATA_CACHE_L2_TTL", "86400"))                   # 24h
REDIS_TIMEOUT = int(os.getenv("DATA_CACHE_REDIS_TIMEOUT", "2"))            # 2s
WARM_UP_DELAY = int(os.getenv("DATA_CACHE_WARM_UP_DELAY", "30"))            # 30s


class DataCache:
    """统一数据缓存 - 服务 7 个 read 端点."""
    
    _instance: Optional["DataCache"] = None
    _instance_lock = threading.Lock()
    
    def __init__(self):
        # L1: 线程安全 (RLock 支持重入)
        self._lock = threading.RLock()
        self._redis_lock = threading.Lock()  # 保护 _get_redis 延迟初始化
        # L1 main
        self._main: Optional[List[dict]] = None
        self._main_loaded_at: float = 0.0
        # L1 filters: filter_sig → [indices into _main]
        self._filters: Dict[str, List[int]] = {}
        self._filters_loaded_at: Dict[str, float] = {}
        # L2: 同步 redis 客户端 (decode_responses=False for gzip bytes)
        self._redis_client = None
        self._redis_available: Optional[bool] = None
        # Pub/Sub: web 容器 listener task
        self._pubsub_task: Optional[asyncio.Task] = None
        # 统计
        self._stats = {
            "l1_hits": 0, "l2_hits": 0, "db_loads": 0,
            "invalidations": 0, "filter_hits": 0, "filter_misses": 0,
        }
    
    @classmethod
    def instance(cls) -> "DataCache":
        """全局单例 (线程安全)."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    # ━━━ L1/L2 Redis ━━━
    def _get_redis(self):
        """延迟初始化 sync redis 客户端, 失败时返回 None."""
        if self._redis_client is not None or self._redis_available is False:
            return self._redis_client
        with self._redis_lock:
            # Double-check: 可能在等锁期间已被其他线程初始化
            if self._redis_client is not None or self._redis_available is False:
                return self._redis_client
            try:
                import redis as redis_lib
                self._redis_client = redis_lib.Redis.from_url(
                    REDIS_URL, decode_responses=False, socket_timeout=REDIS_TIMEOUT
                )
                self._redis_client.ping()
                self._redis_available = True
                logger.info(f"[DataCache] Redis 已连接: {REDIS_URL}")
            except Exception as e:
                logger.warning(f"[DataCache] Redis 不可用 ({e}), 降级到 L1 only")
                self._redis_client = None
                self._redis_available = False
        return self._redis_client
    
    # ━━━ Main Cache API ━━━
    def get_main(self) -> Tuple[Optional[List[dict]], int, str]:
        """获取主项目列表 (108k items). 同步 (FastAPI 兼容).
        
        Returns:
            (projects, total, source) - source ∈ {"l1", "l2", "miss"}
        """
        now = time.time()
        # L1
        with self._lock:
            if (
                self._main is not None
                and (now - self._main_loaded_at) < IN_PROCESS_TTL_MAIN
            ):
                self._stats["l1_hits"] += 1
                return self._main, len(self._main), "l1"
        
        # L2
        client = self._get_redis()
        if client is not None:
            try:
                raw = client.get(REDIS_KEY_MAIN)
                if raw:
                    if isinstance(raw, bytes) and len(raw) >= 2 and raw[0:2] == b"\x1f\x8b":
                        decompressed = gzip.decompress(raw).decode("utf-8")
                    elif isinstance(raw, str):
                        decompressed = raw
                    else:
                        decompressed = raw.decode("utf-8")
                    payload = json.loads(decompressed)
                    projects = payload.get("projects", [])
                    with self._lock:
                        self._main = projects
                        self._main_loaded_at = now
                        # main 变了, filter 索引失效
                        self._filters.clear()
                        self._filters_loaded_at.clear()
                    self._stats["l2_hits"] += 1
                    logger.info(f"[DataCache] L2 Redis 命中 main ({len(projects)} 条)")
                    return projects, len(projects), "l2"
            except Exception as e:
                logger.warning(f"[DataCache] Redis 读取失败: {e}")
        
        return None, 0, "miss"
    
    def set_main(self, projects: List[dict], total: int) -> None:
        """写入 L1 (同步) + L2 (异步后台)."""
        now = time.time()
        with self._lock:
            self._main = projects
            self._main_loaded_at = now
            # main 变了, filter 索引失效
            self._filters.clear()
            self._filters_loaded_at.clear()
        self._stats["db_loads"] += 1
        # L2 异步写入 (不阻塞当前请求)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._l2_write_async(projects, total))
        except RuntimeError:
            # 没有 running loop (e.g. startup / 测试) - 直接同步写
            self._l2_write_sync(projects, total)
    
    def _l2_write_sync(self, projects: List[dict], total: int) -> None:
        """同步 L2 写入 (供 startup / 无 loop 时用)."""
        client = self._get_redis()
        if client is None:
            return
        try:
            payload = json.dumps({"projects": projects, "total": total}, ensure_ascii=False, default=str)
            compressed = gzip.compress(payload.encode("utf-8"))
            client.setex(REDIS_KEY_MAIN, REDIS_TTL, compressed)
            logger.info(f"[DataCache] L2 同步写入 ({len(projects)} 条, 压缩后 {len(compressed):,}B)")
        except Exception as e:
            logger.warning(f"[DataCache] L2 同步写入失败: {e}")
    
    async def _l2_write_async(self, projects: List[dict], total: int) -> None:
        """异步 L2 写入 (在 thread pool 跑 gzip + setex, 不阻塞事件循环)."""
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self._l2_write_sync, projects, total)
        except Exception as e:
            logger.warning(f"[DataCache] L2 异步写入失败: {e}")
    
    # ━━━ Filter Cache API ━━━
    def get_filter(self, filter_sig: str) -> Optional[List[int]]:
        """获取 filter 索引列表.
        
        Args:
            filter_sig: filter signature string (由调用方构造)
        
        Returns:
            索引列表 (指向 main list), 或 None (未命中)
        """
        with self._lock:
            if filter_sig in self._filters:
                age = time.time() - self._filters_loaded_at[filter_sig]
                if age < IN_PROCESS_TTL_FILTER and self._main is not None:
                    self._stats["filter_hits"] += 1
                    return self._filters[filter_sig]
        self._stats["filter_misses"] += 1
        return None
    
    def set_filter(self, filter_sig: str, indices: List[int]) -> None:
        """写入 filter 索引列表."""
        with self._lock:
            self._filters[filter_sig] = indices
            self._filters_loaded_at[filter_sig] = time.time()
    
    # ━━━ Invalidation ━━━
    def invalidate(self, scope: str = "all") -> Dict[str, Any]:
        """清缓存 (同步, async-safe via RLock).
        
        Args:
            scope: "all" | "main" | "filters"
        """
        result = {"scope": scope, "l1_cleared": False, "l2_cleared": False, "errors": []}
        with self._lock:
            if scope in ("all", "main"):
                self._main = None
                self._main_loaded_at = 0.0
                result["l1_cleared"] = True
            if scope in ("all", "filters"):
                self._filters.clear()
                self._filters_loaded_at.clear()
        if scope in ("all", "main"):
            client = self._get_redis()
            if client is not None:
                try:
                    client.delete(REDIS_KEY_MAIN)
                    result["l2_cleared"] = True
                except Exception as e:
                    result["errors"].append(f"l2: {e}")
        self._stats["invalidations"] += 1
        logger.info(f"[DataCache] invalidate({scope}): {result}")
        return result
    
    # ━━━ Pub/Sub (web 容器订阅) ━━━
    async def start_pubsub_listener(self) -> None:
        """启动 Pub/Sub 监听 (web 容器启动时调用 1 次)."""
        if self._pubsub_task is not None and not self._pubsub_task.done():
            logger.info("[DataCache] Pub/Sub listener 已在运行")
            return
        try:
            loop = asyncio.get_running_loop()
            self._pubsub_task = loop.create_task(self._pubsub_loop())
            logger.info(f"[DataCache] Pub/Sub listener 已调度, 频道: {REDIS_PUBSUB_CHANNEL}, task={self._pubsub_task}")
        except RuntimeError as e:
            logger.error(f"[DataCache] Pub/Sub 启动失败: {e}")
    
    async def stop_pubsub_listener(self) -> None:
        """停止 Pub/Sub 监听 (web 容器关闭时调用)."""
        if self._pubsub_task is not None:
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except asyncio.CancelledError:
                pass
            self._pubsub_task = None
    
    async def _pubsub_loop(self) -> None:
        """Pub/Sub 监听循环 (使用 async redis 客户端)."""
        import redis.asyncio as redis_async
        while True:
            try:
                client = redis_async.from_url(REDIS_URL, decode_responses=True, socket_timeout=None)
                pubsub = client.pubsub()
                await pubsub.subscribe(REDIS_PUBSUB_CHANNEL)
                logger.info(f"[DataCache] Pub/Sub 已订阅 {REDIS_PUBSUB_CHANNEL}")
                async for msg in pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    scope = msg.get("data", "all")
                    logger.info(f"[DataCache] 收到 invalidate 消息: scope={scope}")
                    # 在 thread pool 跑 invalidate (避免阻塞)
                    await asyncio.get_event_loop().run_in_executor(None, self.invalidate, scope)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[DataCache] Pub/Sub 异常, 5s 后重连: {e}")
                await asyncio.sleep(5)
    
    @staticmethod
    def publish_invalidate(scope: str = "all") -> None:
        """发布失效消息 (采集器/调度器调用, 同步, ~5ms).
        
        Args:
            scope: "all" | "main" | "filters"
        """
        try:
            import redis as redis_lib
            client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
            client.publish(REDIS_PUBSUB_CHANNEL, scope)
        except Exception as e:
            logger.warning(f"[DataCache] publish_invalidate 失败: {e}")
    
    # ━━━ 预热 (web 容器启动后异步) ━━━
    async def warm_up(self) -> None:
        """异步预热 - 检查 L2 状态并加载到 L1.
        
        - L2 有数据: deserialize 到 L1 (~800ms)
        - L2 没数据: 留给下次请求时按需加载
        """
        await asyncio.sleep(WARM_UP_DELAY)  # 等 web 完全启动
        logger.info("[DataCache] 预热开始...")
        # 在 thread pool 跑 (不阻塞事件循环)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._warm_up_sync)
    
    def _warm_up_sync(self) -> None:
        """预热的同步部分."""
        # 检查 L2
        client = self._get_redis()
        if client is None:
            logger.info("[DataCache] 预热跳过: Redis 不可用")
            return
        try:
            exists = client.exists(REDIS_KEY_MAIN)
            if not exists:
                logger.info("[DataCache] 预热跳过: L2 无数据")
                return
            # L2 有数据, 触发 get_main 加载到 L1
            projects, total, source = self.get_main()
            if source == "l2":
                logger.info(f"[DataCache] 预热完成: L2→L1 ({total} 条)")
            else:
                logger.info(f"[DataCache] 预热完成: source={source}")
        except Exception as e:
            logger.warning(f"[DataCache] 预热失败: {e}")
    
    # ━━━ 统计 / 健康检查 ━━━
    def stats(self) -> Dict[str, Any]:
        """返回缓存状态."""
        with self._lock:
            l1_alive = (
                self._main is not None
                and (time.time() - self._main_loaded_at) < IN_PROCESS_TTL_MAIN
            )
            l1_count = len(self._main) if self._main else 0
            l1_age = (
                round(time.time() - self._main_loaded_at, 1)
                if self._main_loaded_at > 0 else -1
            )
            filter_count = len(self._filters)
        return {
            "l1": {
                "alive": l1_alive,
                "age_seconds": l1_age,
                "ttl_seconds": IN_PROCESS_TTL_MAIN,
                "count": l1_count,
                "filters_cached": filter_count,
            },
            "l2": {
                "available": self._redis_available,
                "key": REDIS_KEY_MAIN,
                "ttl_seconds": REDIS_TTL,
                "pubsub_channel": REDIS_PUBSUB_CHANNEL,
            },
            "stats": dict(self._stats),
        }
    
    def reset_stats(self) -> None:
        """重置统计 (测试用)."""
        with self._lock:
            self._stats = {
                "l1_hits": 0, "l2_hits": 0, "db_loads": 0,
                "invalidations": 0, "filter_hits": 0, "filter_misses": 0,
            }


# ━━━ 全局单例 ━━━
data_cache = DataCache.instance()
