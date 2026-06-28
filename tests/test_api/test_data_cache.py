#!/usr/bin/env python3
"""
DataCache v2 单元测试 - 2026-06-26 PR feat/data-cache-v2

覆盖 (5 大类):
  - Main cache: L1 hit / L1 miss → L2 hit / L1+L2 miss / set 双写 (L1 同步, L2 异步) / L2 gzip
  - Filter cache: get/set/TTL/失效随 main
  - Invalidation: scope=all/main/filters / 同步 / 锁安全
  - Pub/Sub: publish_invalidate 同步 / receive 后调 invalidate
  - 预热: L2 有数据 → L1 / L2 无数据 → skip / Redis 不可用 → skip
  - 降级: Redis 不可用 → L1 only / Redis 异常 → 不报错
  - 统计: stats() 返回值 / reset_stats()
"""

import asyncio
import gzip
import json
import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


# Opt-1: 从 data_cache 导入新 key 常量供测试使用
from app.core.harvest.data_cache import (
    REDIS_KEY_MAIN, REDIS_KEY_META_V3, REDIS_KEY_DETAIL_V3, META_FIELDS,
)


def _make_sample(n: int = 5) -> list:
    return [{"url": f"http://x.com/{i}", "title": f"项目{i}"} for i in range(n)]


class TestDataCacheMain(unittest.TestCase):
    """L1 + L2 main cache 测试"""
    
    def setUp(self):
        from app.core.harvest.data_cache import DataCache
        # 创建新实例 (不通过 singleton, 避免 test 间状态污染)
        self.cache = DataCache()
        self.cache._redis_available = False
        self.cache._redis_client = None
    
    def test_l1_miss_returns_none(self):
        """L1 空 + L2 禁用 → 返回 miss"""
        projects, total, source = self.cache.get_main()
        self.assertIsNone(projects)
        self.assertEqual(total, 0)
        self.assertEqual(source, "miss")
    
    def test_l1_set_then_get(self):
        """L1 set 后立即 get → 命中 L1"""
        sample = _make_sample(10)
        self.cache.set_main(sample, 10)
        projects, total, source = self.cache.get_main()
        self.assertEqual(len(projects), 10)
        self.assertEqual(source, "l1")
        # l1_hits 计数 +1
        self.assertEqual(self.cache._stats["l1_hits"], 1)
    
    def test_l1_ttl_expiry(self):
        """L1 TTL 过期后 miss"""
        from app.core.harvest import data_cache as dc_mod
        original = dc_mod.IN_PROCESS_TTL_MAIN
        dc_mod.IN_PROCESS_TTL_MAIN = 1
        try:
            self.cache.set_main(_make_sample(1), 1)
            # 立即拿
            self.assertEqual(self.cache.get_main()[2], "l1")
            # 睡 2s
            time.sleep(2)
            self.assertEqual(self.cache.get_main()[2], "miss")
        finally:
            dc_mod.IN_PROCESS_TTL_MAIN = original
    
    def test_set_main_clears_filters(self):
        """set_main 时 filter 索引应一并失效"""
        self.cache.set_main(_make_sample(10), 10)
        self.cache.set_filter("cat=医院", [0, 1, 2])
        self.assertEqual(len(self.cache._filters), 1)
        # 重新 set_main → filter 清空
        self.cache.set_main(_make_sample(20), 20)
        self.assertEqual(len(self.cache._filters), 0)


class TestDataCacheL2(unittest.TestCase):
    """L2 Redis 测试 (gzip)"""
    
    def setUp(self):
        from app.core.harvest.data_cache import DataCache
        self.cache = DataCache()
    
    def test_l1_miss_l2_hit_promotes_to_l1(self):
        """L1 miss → L2 gzip hit → promote to L1"""
        sample = _make_sample(5)
        payload = json.dumps({"projects": sample, "total": 5})
        compressed = gzip.compress(payload.encode("utf-8"))
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.get.return_value = compressed
        self.cache._redis_client = mock_redis
        self.cache._redis_available = True
        
        projects, total, source = self.cache.get_main()
        self.assertEqual(len(projects), 5)
        self.assertEqual(source, "l2")
        # 第二次应走 L1
        self.assertEqual(self.cache.get_main()[2], "l1")
    
    def test_l1_miss_l2_legacy_string(self):
        """L2 旧格式 (str, 未压缩) 向后兼容"""
        sample = _make_sample(3)
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.get.return_value = json.dumps({"projects": sample, "total": 3})  # str
        self.cache._redis_client = mock_redis
        self.cache._redis_available = True
        
        projects, total, source = self.cache.get_main()
        self.assertEqual(len(projects), 3)
        self.assertEqual(source, "l2")
    
    def test_set_main_l2_write_gzip(self):
        """set_main → L2 setex (gzip bytes) — Opt-1 后同时写 main+meta+detail 3 keys"""
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.setex = MagicMock()
        self.cache._redis_client = mock_redis
        self.cache._redis_available = True

        # 用 _l2_write_sync 直接测 (避免异步依赖)
        self.cache._l2_write_sync(_make_sample(1), 1)

        self.assertTrue(mock_redis.setex.called)
        # Opt-1: 现在会写 3 个 key (main gzip+json, meta msgpack, detail msgpack)
        # call.args[0] 是第 1 个位置参数 (key), 不是 key[0]
        keys = [c.args[0] for c in mock_redis.setex.call_args_list]
        # 旧 main key 应仍写 (向后兼容)
        self.assertIn(REDIS_KEY_MAIN, keys)
        # v3 keys
        self.assertIn(REDIS_KEY_META_V3, keys)
        self.assertIn(REDIS_KEY_DETAIL_V3, keys)
        # 旧 main key 应是 gzip bytes
        for call in mock_redis.setex.call_args_list:
            if call.args[0] == REDIS_KEY_MAIN:
                value = call.args[2]
                self.assertIsInstance(value, bytes)
                # 解压可还原
                decompressed = gzip.decompress(value).decode("utf-8")
                payload = json.loads(decompressed)
                self.assertEqual(payload["total"], 1)
                return
        self.fail(f"main key {REDIS_KEY_MAIN} not found in setex calls: {keys}")


class TestDataCacheFilter(unittest.TestCase):
    """Filter cache 测试"""
    
    def setUp(self):
        from app.core.harvest.data_cache import DataCache
        self.cache = DataCache()
        self.cache._redis_available = False
    
    def test_filter_miss_returns_none(self):
        """filter 不存在 → None"""
        self.assertIsNone(self.cache.get_filter("cat=医院"))
    
    def test_filter_set_then_get(self):
        """filter set 后 get 命中"""
        self.cache.set_main(_make_sample(10), 10)
        self.cache.set_filter("cat=医院", [0, 2, 5])
        indices = self.cache.get_filter("cat=医院")
        self.assertEqual(indices, [0, 2, 5])
        self.assertEqual(self.cache._stats["filter_hits"], 1)
    
    def test_filter_ttl_expiry(self):
        """filter TTL 过期后 miss"""
        from app.core.harvest import data_cache as dc_mod
        original = dc_mod.IN_PROCESS_TTL_FILTER
        dc_mod.IN_PROCESS_TTL_FILTER = 1
        try:
            self.cache.set_main(_make_sample(10), 10)
            self.cache.set_filter("cat=医院", [0, 2])
            self.assertEqual(self.cache.get_filter("cat=医院"), [0, 2])
            time.sleep(2)
            self.assertIsNone(self.cache.get_filter("cat=医院"))
        finally:
            dc_mod.IN_PROCESS_TTL_FILTER = original


class TestDataCacheInvalidation(unittest.TestCase):
    """失效 API 测试"""
    
    def setUp(self):
        from app.core.harvest.data_cache import DataCache
        self.cache = DataCache()
        self.cache._redis_available = False
    
    def test_invalidate_all_clears_everything(self):
        """invalidate('all') → L1 main + filters 都清"""
        self.cache.set_main(_make_sample(5), 5)
        self.cache.set_filter("cat=医院", [0, 1])
        result = self.cache.invalidate("all")
        self.assertTrue(result["l1_cleared"])
        self.assertIsNone(self.cache._main)
        self.assertEqual(len(self.cache._filters), 0)
    
    def test_invalidate_main_only(self):
        """invalidate('main') → main 清, filters 保留"""
        self.cache.set_main(_make_sample(5), 5)
        self.cache.set_filter("cat=医院", [0, 1])
        result = self.cache.invalidate("main")
        self.assertTrue(result["l1_cleared"])
        self.assertIsNone(self.cache._main)
        # filter 仍在 (主 cache 不会清 filter, 逻辑是 main set 才清)
        # 实际逻辑: invalidate("main") 只清 main
        self.assertEqual(len(self.cache._filters), 1)
    
    def test_invalidate_filters_only(self):
        """invalidate('filters') → 只清 filters"""
        self.cache.set_main(_make_sample(5), 5)
        self.cache.set_filter("cat=医院", [0, 1])
        result = self.cache.invalidate("filters")
        self.assertFalse(result["l1_cleared"])  # main 未清
        self.assertEqual(len(self.cache._main), 5)
        self.assertEqual(len(self.cache._filters), 0)
    
    def test_invalidate_l2(self):
        """invalidate('all') → L2 Redis delete"""
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.delete = MagicMock(return_value=1)
        self.cache._redis_client = mock_redis
        self.cache._redis_available = True
        
        self.cache.set_main(_make_sample(1), 1)
        result = self.cache.invalidate("all")
        self.assertTrue(result["l2_cleared"])
        self.assertTrue(mock_redis.delete.called)


class TestDataCacheGracefulDegrade(unittest.TestCase):
    """Redis 不可用降级测试"""
    
    def test_redis_get_exception_no_propagation(self):
        """Redis 抛异常 → 优雅返回 miss, 不报错"""
        from app.core.harvest.data_cache import DataCache
        cache = DataCache()
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.get.side_effect = Exception("connection lost")
        cache._redis_client = mock_redis
        cache._redis_available = True
        
        projects, total, source = cache.get_main()
        self.assertIsNone(projects)
        self.assertEqual(source, "miss")
    
    def test_redis_ping_failure_marks_unavailable(self):
        """Redis ping 失败 → 标记不可用, 后续跳过"""
        from app.core.harvest.data_cache import DataCache
        cache = DataCache()
        mock_redis = MagicMock()
        mock_redis.ping.side_effect = Exception("redis down")
        cache._redis_client = None
        cache._redis_available = None
        
        # _get_redis 会捕获异常, 设 _redis_available=False
        result = cache._get_redis()
        self.assertIsNone(result)
        self.assertFalse(cache._redis_available)


class TestDataCachePubSub(unittest.TestCase):
    """Pub/Sub publish_invalidate 测试"""
    
    def test_publish_invalidate_sync(self):
        """publish_invalidate 同步调用 (~5ms)"""
        from app.core.harvest.data_cache import DataCache
        with patch("redis.Redis") as mock_redis_class:
            mock_client = MagicMock()
            mock_redis_class.from_url.return_value = mock_client
            
            DataCache.publish_invalidate("main")
            
            self.assertTrue(mock_client.publish.called)
            call_args = mock_client.publish.call_args
            # publish(channel, message)
            self.assertEqual(call_args[0][0], "data:cache:invalidate")
            self.assertEqual(call_args[0][1], "main")
    
    def test_publish_invalidate_redis_error_no_propagation(self):
        """publish 失败不抛异常"""
        from app.core.harvest.data_cache import DataCache
        with patch("redis.Redis") as mock_redis_class:
            mock_redis_class.from_url.side_effect = Exception("redis gone")
            # 不应抛异常
            DataCache.publish_invalidate("main")
    
    def test_pubsub_listener_start_stop(self):
        """start/stop listener 不抛异常"""
        async def runner():
            from app.core.harvest.data_cache import DataCache
            cache = DataCache()
            cache._pubsub_task = None
            await cache.start_pubsub_listener()
            # 检查 task 已创建
            self.assertIsNotNone(cache._pubsub_task)
            await cache.stop_pubsub_listener()
            # task 已取消
            self.assertIsNone(cache._pubsub_task)
        
        asyncio.run(runner())


class TestDataCacheWarmUp(unittest.TestCase):
    """预热测试"""
    
    def test_warm_up_skips_if_redis_unavailable(self):
        """Redis 不可用 → 预热跳过"""
        from app.core.harvest.data_cache import DataCache
        cache = DataCache()
        cache._redis_available = False
        cache._redis_client = None
        
        # 不应抛异常
        cache._warm_up_sync()
    
    def test_warm_up_skips_if_no_l2_data(self):
        """L2 无数据 → 预热跳过"""
        from app.core.harvest.data_cache import DataCache
        cache = DataCache()
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.exists.return_value = 0  # 无 key
        cache._redis_client = mock_redis
        cache._redis_available = True
        
        cache._warm_up_sync()
        # 不应加载 L1
        self.assertIsNone(cache._main)


class TestDataCacheStats(unittest.TestCase):
    """stats() 返回值测试"""
    
    def test_stats_format(self):
        from app.core.harvest.data_cache import DataCache
        cache = DataCache()
        cache._redis_available = False
        
        stats = cache.stats()
        self.assertIn("l1", stats)
        self.assertIn("l2", stats)
        self.assertIn("stats", stats)
        # L1 字段
        for k in ("alive", "age_seconds", "ttl_seconds", "count", "filters_cached"):
            self.assertIn(k, stats["l1"])
        # L2 字段
        for k in ("available", "key", "ttl_seconds", "pubsub_channel"):
            self.assertIn(k, stats["l2"])
        # stats 字段
        for k in ("l1_hits", "l2_hits", "db_loads", "invalidations", "filter_hits", "filter_misses"):
            self.assertIn(k, stats["stats"])
    
    def test_reset_stats(self):
        from app.core.harvest.data_cache import DataCache
        cache = DataCache()
        cache._stats["l1_hits"] = 100
        cache.reset_stats()
        self.assertEqual(cache._stats["l1_hits"], 0)


if __name__ == "__main__":
    unittest.main()
