#!/usr/bin/env python3
"""
Redis 缓存管理 — 采集结果缓存 / TokenBucket 限速 / 分布式锁
用于政府采购采集系统的缓存层和并发控制
"""

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import redis.asyncio as redis
from redis.asyncio.client import Redis

# ── 配置 ────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL_DEFAULT = int(os.getenv("CACHE_TTL_DEFAULT", "3600"))      # 1h
CACHE_TTL_HARVEST = int(os.getenv("CACHE_TTL_HARVEST", "86400"))      # 24h
LOCK_TIMEOUT = int(os.getenv("CACHE_LOCK_TIMEOUT", "30"))           # 30s
LOCK_BLOCKING_TIMEOUT = int(os.getenv("CACHE_LOCK_BLOCKING_TIMEOUT", "10"))  # 10s


logger = logging.getLogger(__name__)

# ── Redis 连接池（支持内存回退）────────────────────────
class RedisManager:
    _client: Optional[Redis] = None
    _url: str = REDIS_URL
    # 内存回退：Redis 不可用时使用
    _fallback: dict = {}
    _fallback_time: dict = {}
    _using_fallback: bool = False

    @classmethod
    async def get_client(cls) -> Redis:
        if cls._client is None:
            try:
                cls._client = redis.from_url(
                    cls._url,
                    encoding="utf-8",
                    decode_responses=True,
                    max_connections=20,
                    socket_timeout=3,
                    socket_connect_timeout=3,
                    retry_on_timeout=True,
                )
                await cls._client.ping()
                cls._using_fallback = False
                logger.info(f"Redis connected: {cls._url}")
            except Exception as e:
                logger.warning(f"Redis unavailable ({e}), using in-memory fallback")
                cls._client = None
                cls._using_fallback = True
        return cls._client

    @classmethod
    async def get(cls, key: str) -> Optional[str]:
        """读取 key（Redis 或内存回退）"""
        client = await cls.get_client()
        if client is not None:
            return await client.get(key)
        # 内存回退
        import time
        expiry = cls._fallback_time.get(key, 0)
        if expiry > time.time():
            return cls._fallback.get(key)
        cls._fallback.pop(key, None)
        cls._fallback_time.pop(key, None)
        return None

    @classmethod
    async def set(cls, key: str, value: str, ttl: int = 3600) -> bool:
        """写入 key（Redis 或内存回退）"""
        client = await cls.get_client()
        if client is not None:
            await client.set(key, value, ex=ttl)
            return True
        import time
        cls._fallback[key] = value
        cls._fallback_time[key] = time.time() + ttl
        return True

    @classmethod
    async def close(cls):
        if cls._client:
            await cls._client.close()
            cls._client = None

    @classmethod
    async def ping(cls) -> bool:
        try:
            client = await cls.get_client()
            if client is not None:
                return await client.ping()
            return cls._using_fallback
        except Exception:
            return False

    @classmethod
    def is_using_fallback(cls) -> bool:
        return cls._using_fallback


# ── 缓存管理器 ──────────────────────────────────────────
class CacheManager:
    """采集结果缓存"""

    KEY_PREFIX = "procurement:cache"

    @classmethod
    def _make_key(cls, source: str, identifier: str) -> str:
        """生成缓存键"""
        safe_id = identifier.replace(":", "_").replace("/", "_")[:200]
        return f"{cls.KEY_PREFIX}:{source}:{safe_id}"

    @classmethod
    def _hash_params(cls, params: Dict[str, Any]) -> str:
        """对字典参数做 SHA256 哈希（用于查询缓存）"""
        canonical = json.dumps(params, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:32]

    @classmethod
    async def get(cls, source: str, identifier: str) -> Optional[Any]:
        """读取缓存"""
        key = cls._make_key(source, identifier)
        try:
            client = await RedisManager.get_client()
            data = await client.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.warning(f"Cache GET error {key}: {e}")
        return None

    @classmethod
    async def set(
        cls,
        source: str,
        identifier: str,
        value: Any,
        ttl: int = CACHE_TTL_HARVEST,
    ) -> bool:
        """写入缓存"""
        key = cls._make_key(source, identifier)
        try:
            client = await RedisManager.get_client()
            await client.setex(key, ttl, json.dumps(value, ensure_ascii=True))
            return True
        except Exception as e:
            logger.warning(f"Cache SET error {key}: {e}")
            return False

    @classmethod
    async def delete(cls, source: str, identifier: str) -> bool:
        """删除缓存"""
        key = cls._make_key(source, identifier)
        try:
            client = await RedisManager.get_client()
            await client.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Cache DELETE error {key}: {e}")
            return False

    @classmethod
    async def get_or_fetch(
        cls,
        source: str,
        identifier: str,
        fetch_fn,
        ttl: int = CACHE_TTL_HARVEST,
    ) -> Any:
        """
        缓存读取模式：先读缓存，miss 时调用 fetch_fn 并写入缓存。
        fetch_fn 必须是 async 函数。
        """
        cached = await cls.get(source, identifier)
        if cached is not None:
            return cached

        fresh = await fetch_fn()
        if fresh is not None:
            await cls.set(source, identifier, fresh, ttl=ttl)
        return fresh

    @classmethod
    async def invalidate_source(cls, source: str) -> int:
        """清除指定来源的所有缓存（pattern 匹配）"""
        pattern = f"{cls.KEY_PREFIX}:{source}:*"
        try:
            client = await RedisManager.get_client()
            keys = []
            async for key in client.scan_iter(match=pattern, count=200):
                keys.append(key)
            if keys:
                return await client.delete(*keys)
        except Exception as e:
            logger.warning(f"Cache invalidate error for {source}: {e}")
        return 0

    @classmethod
    async def get_many(cls, source: str, identifiers: List[str]) -> Dict[str, Any]:
        """批量读取缓存"""
        if not identifiers:
            return {}
        keys = [cls._make_key(source, i) for i in identifiers]
        try:
            client = await RedisManager.get_client()
            values = await client.mget(keys)
            result = {}
            for ident, val in zip(identifiers, values):
                if val:
                    result[ident] = json.loads(val)
            return result
        except Exception as e:
            logger.warning(f"Cache MGET error: {e}")
            return {}

    @classmethod
    async def set_many(
        cls,
        source: str,
        items: Dict[str, Any],
        ttl: int = CACHE_TTL_HARVEST,
    ) -> int:
        """批量写入缓存（Pipeline）"""
        if not items:
            return 0
        pipe = None
        try:
            client = await RedisManager.get_client()
            pipe = client.pipeline()
            for ident, value in items.items():
                key = cls._make_key(source, ident)
                pipe.setex(key, ttl, json.dumps(value, ensure_ascii=True))
            results = await pipe.execute()
            return sum(1 for r in results if r)
        except Exception as e:
            logger.warning(f"Cache MSET error: {e}")
            return 0


# ── TokenBucket 限速 ────────────────────────────────────
@dataclass
class TokenBucketConfig:
    """TokenBucket 配置"""
    capacity: int      # 桶容量（最多累积 token 数）
    refill_rate: float  # 每秒补充 token 数（= RPM / 60）

    @classmethod
    def from_rpm(cls, rpm: int, burst: Optional[int] = None) -> "TokenBucketConfig":
        """从 requests-per-minute 转换为 TokenBucket"""
        capacity = burst if burst is not None else max(rpm, 10)
        refill_rate = rpm / 60.0
        return cls(capacity=capacity, refill_rate=refill_rate)


class TokenBucketRateLimiter:
    """
    基于 Redis 的分布式 TokenBucket 限速器。
    使用 Lua 脚本保证原子性。

    键格式: rate_limit:tokens:{source_name}
    """

    KEY_PREFIX = "rate_limit:tokens"

    LUA_SCRIPT = """
    local key = KEYS[1]
    local capacity = tonumber(ARGV[1])
    local refill_rate = tonumber(ARGV[2])
    local now = tonumber(ARGV[3])
    local requested = tonumber(ARGV[4])

    local data = redis.call('HMGET', key, 'tokens', 'last_update')
    local tokens = tonumber(data[1])
    local last_update = tonumber(data[2])

    if tokens == nil then
        tokens = capacity
        last_update = now
    end

    -- 补充 tokens
    local elapsed = now - last_update
    local add = elapsed * refill_rate
    tokens = math.min(capacity, tokens + add)

    local allowed = 0
    if tokens >= requested then
        tokens = tokens - requested
        allowed = 1
    end

    redis.call('HMSET', key, 'tokens', tokens, 'last_update', now)
    redis.call('EXPIRE', key, math.ceil((capacity - tokens) / refill_rate) + 10)

    return {allowed, tokens}
    """

    _script_sha: Optional[str] = None

    @classmethod
    async def _get_script_sha(cls, client: Redis) -> str:
        if cls._script_sha is None:
            cls._script_sha = await client.script_load(cls.LUA_SCRIPT)
        return cls._script_sha

    @classmethod
    def _key(cls, source_name: str) -> str:
        return f"{cls.KEY_PREFIX}:{source_name}"

    @classmethod
    async def try_acquire(
        cls,
        source_name: str,
        config: TokenBucketConfig,
        tokens: int = 1,
    ) -> tuple[bool, float]:
        """
        尝试获取 token。
        返回 (allowed, remaining_tokens)。

        注意：此方法不阻塞等待，allowed=False 时需自行决定重试。
        """
        try:
            client = await RedisManager.get_client()
            sha = await cls._get_script_sha(client)
            now = time.time()
            result = await client.evalsha(
                sha,
                1,  # number of keys
                cls._key(source_name),
                config.capacity,
                config.refill_rate,
                now,
                tokens,
            )
            allowed = bool(result[0])
            remaining = float(result[1])
            return allowed, remaining
        except redis.exceptions.NoScriptError:
            # script not cached, fallback to eval directly
            cls._script_sha = None
            return await cls.try_acquire(source_name, config, tokens)
        except Exception as e:
            logger.warning(f"TokenBucket error for {source_name}: {e}")
            # Fail open: 限速器故障时允许请求（保守策略可改为 deny）
            return True, 0.0

    @classmethod
    @asynccontextmanager
    async def acquire_context(
        cls,
        source_name: str,
        config: TokenBucketConfig,
        tokens: int = 1,
        timeout: float = 30.0,
    ):
        """
        上下文管理器：阻塞等待直到获取到 token 或超时。
        用法:
            async with TokenBucketRateLimiter.acquire_context('ccgp', config):
                await fetch_page(url)
        """
        deadline = time.time() + timeout
        while True:
            allowed, remaining = await cls.try_acquire(source_name, config, tokens)
            if allowed:
                yield remaining
                return

            wait_time = (tokens - remaining) / config.refill_rate if config.refill_rate > 0 else 1.0
            wait_time = min(wait_time, deadline - time.time())
            if wait_time <= 0:
                raise TimeoutError(f"Rate limit timeout for {source_name} after {timeout}s")

            await asyncio.sleep(min(wait_time, 0.5))

    @classmethod
    async def get_status(cls, source_name: str) -> Dict[str, Any]:
        """查询限速器当前状态"""
        key = cls._key(source_name)
        try:
            client = await RedisManager.get_client()
            data = await client.hgetall(key)
            if not data:
                return {"status": "idle", "tokens": None, "capacity": None}
            return {
                "status": "active",
                "tokens": float(data.get("tokens", 0)),
                "last_update": float(data.get("last_update", 0)),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @classmethod
    async def reset(cls, source_name: str) -> bool:
        """重置限速器状态（清空 token）"""
        try:
            client = await RedisManager.get_client()
            await client.delete(cls._key(source_name))
            return True
        except Exception as e:
            logger.warning(f"TokenBucket reset error for {source_name}: {e}")
            return False


# ── 分布式锁 ────────────────────────────────────────────
class DistributedLock:
    """
    Redis 分布式锁（使用 SET NX EX 实现，支持自动续期）。
    键格式: lock:{resource}
    """

    KEY_PREFIX = "lock"

    def __init__(
        self,
        resource: str,
        timeout: int = LOCK_TIMEOUT,
        blocking_timeout: float = LOCK_BLOCKING_TIMEOUT,
        token: Optional[str] = None,
    ):
        self.resource = resource
        self.key = f"{self.KEY_PREFIX}:{resource}"
        self.timeout = timeout
        self.blocking_timeout = blocking_timeout
        self.token = token or str(uuid.uuid4())
        self._locked = False

    @property
    def is_locked(self) -> bool:
        return self._locked

    async def acquire(self) -> bool:
        """尝试获取锁（非阻塞）"""
        try:
            client = await RedisManager.get_client()
            ok = await client.set(
                self.key,
                self.token,
                nx=True,   # Only set if Not eXists
                ex=self.timeout,  # Expire
            )
            self._locked = bool(ok)
            return self._locked
        except Exception as e:
            logger.warning(f"Lock acquire error for {self.resource}: {e}")
            return False

    async def acquire_blocking(self) -> bool:
        """阻塞获取锁（直到成功或超时）"""
        deadline = time.time() + self.blocking_timeout
        while time.time() < deadline:
            if await self.acquire():
                return True
            await asyncio.sleep(0.05)
        return False

    async def release(self) -> bool:
        """
        释放锁（使用 Lua 脚本保证只释放自己的锁）。
        """
        lua = """
        if redis.call('GET', KEYS[1]) == ARGV[1] then
            return redis.call('DEL', KEYS[1])
        else
            return 0
        end
        """
        try:
            client = await RedisManager.get_client()
            result = await client.eval(lua, 1, self.key, self.token)
            self._locked = False
            return bool(result)
        except Exception as e:
            logger.warning(f"Lock release error for {self.resource}: {e}")
            return False

    async def extend(self, extra_seconds: int = None) -> bool:
        """延长锁的 TTL（自动续期）"""
        extra = extra_seconds or self.timeout
        lua = """
        if redis.call('GET', KEYS[1]) == ARGV[1] then
            return redis.call('EXPIRE', KEYS[1], ARGV[2])
        else
            return 0
        end
        """
        try:
            client = await RedisManager.get_client()
            result = await client.eval(lua, 1, self.key, self.token, extra)
            return bool(result)
        except Exception as e:
            logger.warning(f"Lock extend error for {self.resource}: {e}")
            return False

    async def __aenter__(self) -> "DistributedLock":
        acquired = await self.acquire_blocking()
        if not acquired:
            raise TimeoutError(f"Could not acquire lock for {self.resource}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.release()
        return False


@asynccontextmanager
async def distributed_lock(
    resource: str,
    timeout: int = LOCK_TIMEOUT,
    blocking_timeout: float = LOCK_BLOCKING_TIMEOUT,
):
    """
    分布式锁上下文管理器（简写版本）。

    用法:
        async with distributed_lock("page_fetch:12345"):
            await fetch_page(url)
    """
    lock = DistributedLock(resource, timeout, blocking_timeout)
    try:
        acquired = await lock.acquire_blocking()
        if not acquired:
            raise TimeoutError(f"Could not acquire lock: {resource}")
        yield lock
    finally:
        await lock.release()


# ── 便捷封装 ─────────────────────────────────────────────
class HarvestCache:
    """
    采集业务专用的缓存封装（组合以上组件）。
    """

    @staticmethod
    async def cache_page(source: str, url: str, html: str, ttl: int = CACHE_TTL_HARVEST) -> bool:
        """缓存页面内容"""
        key = hashlib.sha256(url.encode()).hexdigest()[:32]
        return await CacheManager.set(source, f"page:{key}", html, ttl=ttl)

    @staticmethod
    async def get_cached_page(source: str, url: str) -> Optional[str]:
        """读取缓存页面"""
        key = hashlib.sha256(url.encode()).hexdigest()[:32]
        return await CacheManager.get(source, f"page:{key}")

    @staticmethod
    async def cache_json(
        source: str,
        url: str,
        data: Dict[str, Any],
        ttl: int = CACHE_TTL_HARVEST,
    ) -> bool:
        """缓存 JSON 响应"""
        key = hashlib.sha256(url.encode()).hexdigest()[:32]
        return await CacheManager.set(source, f"json:{key}", data, ttl=ttl)

    @staticmethod
    async def get_cached_json(source: str, url: str) -> Optional[Dict[str, Any]]:
        """读取缓存的 JSON"""
        key = hashlib.sha256(url.encode()).hexdigest()[:32]
        return await CacheManager.get(source, f"json:{key}")

    @staticmethod
    async def mark_fetched(url: str, source: str = "global") -> bool:
        """标记 URL 已抓取（去重）"""
        key = hashlib.sha256(url.encode()).hexdigest()
        try:
            client = await RedisManager.get_client()
            await client.setex(f"fetched:{source}:{key}", CACHE_TTL_HARVEST, "1")
            return True
        except Exception as e:
            logger.warning(f"mark_fetched error: {e}")
            return False

    @staticmethod
    async def was_fetched(url: str, source: str = "global") -> bool:
        """检查 URL 是否已抓取"""
        key = hashlib.sha256(url.encode()).hexdigest()
        try:
            client = await RedisManager.get_client()
            val = await client.get(f"fetched:{source}:{key}")
            return val is not None
        except Exception as e:
            logger.warning(f"was_fetched error: {e}")
            return False

    @staticmethod
    async def record_success(source: str, url: str) -> None:
        """记录成功请求（用于统计）"""
        try:
            client = await RedisManager.get_client()
            key = f"stats:success:{source}"
            await client.hincrby(key, url, 1)
            await client.expire(key, 86400)
        except Exception as e:
            logger.warning(f"record_success error: {e}")

    @staticmethod
    async def get_stats(source: str) -> Dict[str, int]:
        """获取抓取统计"""
        try:
            client = await RedisManager.get_client()
            key = f"stats:success:{source}"
            data = await client.hgetall(key)
            return {k: int(v) for k, v in data.items()}
        except Exception as e:
            logger.warning(f"get_stats error: {e}")
            return {}


# ── 健康检查 ─────────────────────────────────────────────
async def health_check() -> Dict[str, Any]:
    """Redis 健康状态检查"""
    try:
        client = await RedisManager.get_client()
        info = await client.info("server")
        return {
            "status": "ok",
            "redis_version": info.get("redis_version", "unknown"),
            "connected": True,
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "connected": False}
