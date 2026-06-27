#!/usr/bin/env python3
"""DataCache Opt-1~5 单元测试 - 2026-06-28 PR feat/cache-opt-v3

覆盖:
  - Opt-1: _split_meta_detail (meta 6 字段 + detail 剩余)
  - Opt-2: msgpack L2 写读 (v3 keys)
  - Opt-3: filter cache 真接入 (set/get + urls + catnum 索引)
  - Opt-4: catnum 桶失效 + _extract_catnums
  - Opt-5: page cache (get/set/失效/stats/FIFO 上限)
"""

import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestOpt1SplitMetaDetail(unittest.TestCase):
    """Opt-1: L2 拆 meta + detail"""

    def test_split_meta_detail_basic(self):
        from app.core.harvest.data_cache import DataCache
        sample = [
            {"url": "a", "title": "A", "type": "工程", "publish_date": "2026-01-01",
             "source_url": "a", "business_type": "工程招投标",
             "content_preview": "xxx", "full_content": "yyy", "budget": "100万"},
        ]
        meta, detail = DataCache._split_meta_detail(sample)
        self.assertEqual(len(meta), 1)
        # meta 仅 6 字段
        self.assertEqual(set(meta[0].keys()),
                         {"url", "title", "type", "publish_date", "source_url", "business_type"})
        # detail 含剩余字段 + url (便于按 url 查找)
        self.assertEqual(detail["a"]["content_preview"], "xxx")
        self.assertEqual(detail["a"]["full_content"], "yyy")
        self.assertEqual(detail["a"]["url"], "a")  # url 保留在 detail
        self.assertNotIn("business_type", detail["a"])

    def test_split_meta_detail_empty(self):
        from app.core.harvest.data_cache import DataCache
        meta, detail = DataCache._split_meta_detail([])
        self.assertEqual(meta, [])
        self.assertEqual(detail, {})


class TestOpt2MsgpackL2(unittest.TestCase):
    """Opt-2: msgpack 替代 gzip+JSON"""

    def test_msgpack_pack_unpack(self):
        import msgpack
        data = {"projects": [{"url": "a", "title": "A"}], "total": 1}
        packed = msgpack.packb(data, use_bin_type=True)
        unpacked = msgpack.unpackb(packed, raw=False)
        self.assertEqual(unpacked["total"], 1)
        self.assertEqual(unpacked["projects"][0]["url"], "a")

    def test_msgpack_smaller_or_equal_to_json(self):
        """验证 msgpack 体积 ≤ JSON (宽松期望: 重键场景下能打平或更优即可)"""
        import json
        import msgpack
        # 短重复键场景: msgpack 不存储重复 key 名, 应不劣于 JSON
        sample = [
            {
                "url": f"http://x.com/{i}",
                "title": f"项目{i}",
                "type": "工程",
                "publish_date": "2026-01-01",
                "source_url": "http://x.com",
                "business_type": "工程招投标",
            }
            for i in range(1000)
        ]
        j = json.dumps(sample, ensure_ascii=False).encode("utf-8")
        m = msgpack.packb(sample, use_bin_type=True)
        # msgpack 体积应 ≤ JSON (生产中 gzip 后者可能更优, 但序列化阶段 msgpack 更快)
        self.assertLessEqual(len(m), len(j),
                             f"msgpack {len(m):,}B 应 ≤ JSON {len(j):,}B")

    def test_msgpack_unpack_is_callable(self):
        """验证 msgpack unpack 接口正确 (实战要点: raw=False 解码字符串)"""
        import msgpack
        sample = [{"url": "a", "title": "测试中文"}]
        packed = msgpack.packb(sample, use_bin_type=True)
        # raw=False 必须, 否则中文变成 bytes
        unpacked = msgpack.unpackb(packed, raw=False)
        self.assertEqual(unpacked[0]["title"], "测试中文")
        # raw=True (默认) key 是 bytes, value 也是 bytes
        unpacked_bytes = msgpack.unpackb(packed, raw=True)
        # bytes key
        self.assertIn(b"title", unpacked_bytes[0])
        # bytes value
        self.assertIsInstance(unpacked_bytes[0][b"title"], bytes)
        self.assertEqual(unpacked_bytes[0][b"title"], "测试中文".encode("utf-8"))


class TestOpt3FilterCache(unittest.TestCase):
    """Opt-3: filter cache 真接入"""

    def setUp(self):
        from app.core.harvest.data_cache import DataCache
        self.dc = DataCache.instance()
        self.dc._filters.clear()
        self.dc._catnum_to_sigs.clear()

    def test_set_get_filter_with_urls(self):
        urls = ["http://x.com/trade/014001001/abc", "http://x.com/trade/014001001/def"]
        self.dc.set_filter("sig_A", urls)
        got = self.dc.get_filter("sig_A")
        self.assertEqual(got, urls)

    def test_filter_cache_works_without_main(self):
        """Opt-3 重设计: filter cache 不依赖 _main 是否加载"""
        urls = ["http://x.com/trade/014001001/abc"]
        self.dc.set_filter("sig_A", urls)
        # _main is None (未加载), 但 filter cache 仍应命中
        self.assertIsNone(self.dc._main)
        got = self.dc.get_filter("sig_A")
        self.assertEqual(got, urls)

    def test_filter_ttl_5min(self):
        """验证 filter cache TTL = 5min (300s)"""
        from app.core.harvest.data_cache import IN_PROCESS_TTL_FILTER
        self.assertEqual(IN_PROCESS_TTL_FILTER, 300)


class TestOpt4CatnumInvalidation(unittest.TestCase):
    """Opt-4: catnum 桶失效"""

    def test_extract_catnums_9_digit(self):
        from app.core.harvest.data_cache import DataCache
        urls = [
            "https://www.cqggzy.com/trade/014001/u1?categoryNum=014001001",
            "https://www.cqggzy.com/trade/014005/u2?categoryNum=014005002",
            "https://www.cqggzy.com/trade/014001/u3?categoryNum=014001019001",  # 12 位子分类
            "https://other.com/no-catnum",
        ]
        catnums = DataCache._extract_catnums(urls)
        self.assertIn("014001001", catnums)
        self.assertIn("014005002", catnums)
        self.assertIn("014001019", catnums)
        # 6 位不应被错误提取
        self.assertNotIn("014001", catnums)
        self.assertNotIn("014005", catnums)

    def test_catnum_bucket_invalidation(self):
        """验证 catnum 失效只清受影响 sig, 不动其他 sig"""
        from app.core.harvest.data_cache import DataCache
        dc = DataCache.instance()
        dc._filters.clear()
        dc._catnum_to_sigs.clear()
        # 两个 sig 涉及不同 catnum
        dc.set_filter("sig_A", ["http://x.com/trade/014001001/u1"])
        dc.set_filter("sig_B", ["http://x.com/trade/014005002/u3"])
        self.assertEqual(len(dc._catnum_to_sigs), 2)

        # 失效 014001001 → sig_A 应被清, sig_B 保留
        result = dc.invalidate("catnum:014001001")
        self.assertEqual(result["filter_sigs_cleared"], 1)
        self.assertIsNone(dc.get_filter("sig_A"))
        self.assertIsNotNone(dc.get_filter("sig_B"))

    def test_catnum_invalidation_invalid_scope_returns_early(self):
        """scope='catnum' (无后缀) 不匹配 startswith('catnum:'), 应当作未知 scope 跳过"""
        from app.core.harvest.data_cache import DataCache
        dc = DataCache.instance()
        dc._filters.clear()
        dc.set_filter("sig", ["http://x.com/trade/014001001/u1"])
        # 无 :xxx 的 scope 不进入 catnum 分支, sig 应保留 (未走任何清路径)
        result = dc.invalidate("catnum")
        self.assertIsNotNone(dc.get_filter("sig"))  # 保留
        self.assertEqual(result["scope"], "catnum")


class TestOpt5PageCache(unittest.TestCase):
    """Opt-5: page-level result cache"""

    def setUp(self):
        from app.core.harvest.data_cache import DataCache
        self.dc = DataCache.instance()
        self.dc._pages.clear()
        self.dc._pages_loaded_at.clear()

    def test_set_get_page(self):
        result = {"projects": [{"url": "a"}, {"url": "b"}], "total": 2, "last_run": "2026-01-01"}
        self.dc.set_page("sig_A", 1, 10, result)
        got = self.dc.get_page("sig_A", 1, 10)
        self.assertIsNotNone(got)
        self.assertEqual(got["total"], 2)
        self.assertEqual(len(got["projects"]), 2)
        self.assertEqual(got["last_run"], "2026-01-01")

    def test_page_cache_isolates_mutations(self):
        """修改返回的 projects 不应污染 cache (copy 验证)"""
        result = {"projects": [{"url": "a"}], "total": 1}
        self.dc.set_page("sig_A", 1, 10, result)
        got = self.dc.get_page("sig_A", 1, 10)
        got["projects"].append({"url": "b"})
        got2 = self.dc.get_page("sig_A", 1, 10)
        self.assertEqual(len(got2["projects"]), 1)  # 未被污染

    def test_page_cache_miss_returns_none(self):
        self.assertIsNone(self.dc.get_page("nonexistent", 1, 10))

    def test_page_cache_key_format(self):
        from app.core.harvest.data_cache import DataCache
        key = DataCache._make_page_key("sig", 1, 10)
        self.assertEqual(key, "sig:1:10")

    def test_invalidate_pages(self):
        self.dc.set_page("sig_A", 1, 10, {"projects": [], "total": 0})
        self.dc.set_page("sig_A", 2, 10, {"projects": [], "total": 0})
        result = self.dc.invalidate("pages")
        self.assertEqual(result["pages_cleared"], 2)
        self.assertIsNone(self.dc.get_page("sig_A", 1, 10))

    def test_invalidate_all_clears_pages(self):
        self.dc.set_page("sig_A", 1, 10, {"projects": [], "total": 0})
        self.dc.invalidate("all")
        self.assertIsNone(self.dc.get_page("sig_A", 1, 10))

    def test_page_cache_max_size(self):
        """超过 _pages_max 时 FIFO 淘汰最早"""
        from app.core.harvest.data_cache import DataCache
        dc = DataCache.instance()
        dc._pages.clear()
        dc._pages_loaded_at.clear()
        # 设置小上限便于测试
        original_max = dc._pages_max
        dc._pages_max = 3
        try:
            for i in range(5):
                dc.set_page(f"sig_{i}", 1, 10, {"projects": [], "total": 0})
                time.sleep(0.01)  # 错开时间戳
            # 5 个写入, 3 个上限 → 最老的 2 个应被淘汰
            self.assertLessEqual(len(dc._pages), 3)
            # sig_0 和 sig_1 应被淘汰 (最早)
            self.assertIsNone(dc.get_page("sig_0", 1, 10))
            self.assertIsNone(dc.get_page("sig_1", 1, 10))
            # sig_4 应保留
            self.assertIsNotNone(dc.get_page("sig_4", 1, 10))
        finally:
            dc._pages_max = original_max

    def test_stats_includes_pages(self):
        """stats() 输出应包含 page_hits/page_misses/pages_cached"""
        from app.core.harvest.data_cache import DataCache
        dc = DataCache.instance()
        dc._pages.clear()
        dc._pages_loaded_at.clear()
        dc.reset_stats()
        # write + read hit
        dc.set_page("sig_A", 1, 10, {"projects": [], "total": 0})
        dc.get_page("sig_A", 1, 10)  # hit
        dc.get_page("missing", 1, 10)  # miss
        s = dc.stats()
        self.assertIn("pages_cached", s["l1"])
        self.assertEqual(s["stats"]["page_hits"], 1)
        self.assertEqual(s["stats"]["page_misses"], 1)

    def test_catnum_invalidate_clears_pages(self):
        """Opt-5: catnum 失效应同步清受影响 sig 的 page entries"""
        from app.core.harvest.data_cache import DataCache
        dc = DataCache.instance()
        dc._pages.clear()
        dc._pages_loaded_at.clear()
        dc._filters.clear()
        dc._catnum_to_sigs.clear()
        dc.set_filter("sig_A", ["http://x.com/trade/014001001/u1"])
        dc.set_page("sig_A", 1, 10, {"projects": [], "total": 0})
        dc.set_page("sig_A", 2, 10, {"projects": [], "total": 0})
        dc.invalidate("catnum:014001001")
        # page cache 应被清
        self.assertIsNone(dc.get_page("sig_A", 1, 10))
        self.assertIsNone(dc.get_page("sig_A", 2, 10))


if __name__ == "__main__":
    unittest.main()
