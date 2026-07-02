#!/usr/bin/env python3
"""
DataCache v4 Delta Sync 单元测试 - 2026-06-29

覆盖 (5 大类):
  - T1: 冷启 full load (L1 miss → L2 hit → delta sync 全量)
  - T2: L1 hit 直接返回 (无 DB 调用)
  - T3: catnum invalidate 标记 pending_delta, 下次 get_main 触发增量 merge
  - T4: invalidate("all") 清 main + 重置 last_main_sync_at
  - T5: stats 含 delta_loads 计数
  - T6: merge 行为: update 现有 url + append 新 url
  - T7: 与 db.delta_load_since 集成 (用 mock DB 避免依赖)

不依赖真实 DB, 用 unittest.mock patch `Database.delta_load_since`.
"""

import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


def _make_rows(urls: list, prefix: str = ""):
    """生成 mock project rows, 必含 url 字段."""
    return [
        {"url": u, "title": f"{prefix}{u}", "publish_date": "2026-06-29",
         "category": "014001001", "business_type": "工程招投标",
         "content_preview": "", "full_content": "", "scraped_at": "2026-06-29",
         "_table": "projects_cqggzy", "_updated_at": "2026-06-29 12:00:00"}
        for u in urls
    ]


class TestDataCacheDeltaV4(unittest.TestCase):
    """v4 delta sync 测试"""

    def setUp(self):
        from app.core.harvest.data_cache import DataCache
        # 新实例 (不走 singleton)
        self.cache = DataCache()
        # 禁用 Redis L2 (避免测试依赖 redis)
        self.cache._redis_available = False
        self.cache._redis_client = None

    def tearDown(self):
        # 避免影响其他 test
        self.cache._main = None
        self.cache._last_main_sync_at = 0.0
        self.cache._pending_delta = False

    def test_t1_cold_start_full_load(self):
        """T1: L1 miss + L2 禁用 → 走 DB delta full load"""
        mock_rows = _make_rows([f"http://x.com/{i}" for i in range(100)])
        with patch("app.database.db.Database") as MockDB:
            mock_db_instance = MockDB.return_value
            mock_db_instance.delta_load_since.return_value = mock_rows

            projects, total, source = self.cache.get_main()

        self.assertEqual(total, 100)
        self.assertEqual(source, "db_full")
        self.assertEqual(len(projects), 100)
        # last_main_sync_at 已记录
        self.assertGreater(self.cache._last_main_sync_at, 0)
        # db_loads 计数 +1
        self.assertEqual(self.cache._stats["db_loads"], 1)

    def test_t2_l1_hit_no_db_call(self):
        """T2: L1 alive → 直接返回, 不调 DB"""
        # 预填充 L1
        rows = _make_rows([f"http://x.com/{i}" for i in range(50)])
        self.cache._main = {r["url"]: r for r in rows}
        self.cache._main_loaded_at = time.time()
        self.cache._last_main_sync_at = time.time()

        with patch("app.database.db.Database") as MockDB:
            projects, total, source = self.cache.get_main()
            MockDB.assert_not_called()  # 没调 DB

        self.assertEqual(source, "l1")
        self.assertEqual(total, 50)
        self.assertEqual(self.cache._stats["l1_hits"], 1)

    def test_t3_catnum_invalidate_marks_pending_delta(self):
        """T3: invalidate('catnum:014001001') → _pending_delta=True"""
        rows = _make_rows([f"http://x.com/{i}" for i in range(50)])
        self.cache._main = {r["url"]: r for r in rows}
        self.cache._main_loaded_at = time.time()
        self.cache._last_main_sync_at = time.time()

        r = self.cache.invalidate("catnum:014001001")
        self.assertTrue(r["delta_pending"])
        self.assertTrue(self.cache._pending_delta)

    def test_t4_get_main_triggers_delta_sync_after_invalidate(self):
        """T4: catnum invalidate 后 get_main → 触发 delta sync"""
        rows_initial = _make_rows([f"http://x.com/{i}" for i in range(50)])
        self.cache._main = {r["url"]: r for r in rows_initial}
        self.cache._main_loaded_at = time.time()
        self.cache._last_main_sync_at = time.time() - 60  # 60s 前同步过

        # catnum invalidate
        self.cache.invalidate("catnum:014001001")
        self.assertTrue(self.cache._pending_delta)

        # 模拟 DB 返回新行
        new_rows = _make_rows(["http://x.com/new1", "http://x.com/new2"], prefix="[NEW]")
        with patch("app.database.db.Database") as MockDB:
            mock_db_instance = MockDB.return_value
            mock_db_instance.delta_load_since.return_value = new_rows

            projects, total, source = self.cache.get_main()

        self.assertEqual(source, "l1+delta")
        self.assertEqual(total, 52)  # 50 + 2 新
        self.assertEqual(self.cache._stats["delta_loads"], 1)
        self.assertFalse(self.cache._pending_delta)  # 已消费

        # 验证新行存在
        urls = {p["url"] for p in projects}
        self.assertIn("http://x.com/new1", urls)
        self.assertIn("http://x.com/new2", urls)

    def test_t5_invalidate_all_resets_sync_state(self):
        """T5: invalidate('all') → _main=None, _last_main_sync_at=0"""
        rows = _make_rows([f"http://x.com/{i}" for i in range(10)])
        self.cache._main = {r["url"]: r for r in rows}
        self.cache._main_loaded_at = time.time()
        self.cache._last_main_sync_at = time.time()

        self.cache.invalidate("all")
        self.assertIsNone(self.cache._main)
        self.assertEqual(self.cache._last_main_sync_at, 0.0)

    def test_t6_merge_update_existing_url(self):
        """T6: merge 时 update 现有 url 的字段"""
        old = {"url": "http://x.com/1", "title": "old", "_updated_at": "2026-06-01"}
        new = {"url": "http://x.com/1", "title": "updated", "_updated_at": "2026-06-29"}
        self.cache._main = {"http://x.com/1": old}
        self.cache._main_loaded_at = time.time()
        self.cache._last_main_sync_at = time.time() - 100

        self.cache._pending_delta = True  # 模拟刚被 invalidate

        with patch("app.database.db.Database") as MockDB:
            mock_db_instance = MockDB.return_value
            mock_db_instance.delta_load_since.return_value = [new]

            projects, total, source = self.cache.get_main()

        self.assertEqual(total, 1)
        self.assertEqual(projects[0]["title"], "updated")  # 已被 new 覆盖

    def test_t7_pending_delta_consumed_after_sync(self):
        """T7: pending_delta 在 delta sync 后被消费 (变 False)"""
        self.cache._main = {}
        self.cache._main_loaded_at = time.time()
        self.cache._last_main_sync_at = time.time()
        self.cache._pending_delta = True

        # DB 返回空 (无新行)
        with patch("app.database.db.Database") as MockDB:
            mock_db_instance = MockDB.return_value
            mock_db_instance.delta_load_since.return_value = []

            projects, total, source = self.cache.get_main()

        # 即便 delta 为空, pending 也应被消费
        self.assertFalse(self.cache._pending_delta)

    def test_t8_stats_include_delta_loads(self):
        """T8: stats() 含 delta_loads 字段"""
        s = self.cache.stats()
        self.assertIn("delta_loads", s["stats"])
        self.assertEqual(s["stats"]["delta_loads"], 0)

    def test_t9_l2_hit_triggers_delta_sync_too(self):
        """T9: L2 hit 后仍触发 delta sync (L2 可能过期, 补足)"""
        # 模拟 L2 有数据
        l2_rows = _make_rows([f"http://x.com/{i}" for i in range(50)])
        # Mock Redis client
        import gzip, json
        mock_client = MagicMock()
        mock_client.get.return_value = gzip.compress(
            json.dumps({"projects": l2_rows, "total": 50}).encode("utf-8")
        )
        self.cache._redis_client = mock_client
        self.cache._redis_available = True

        # 模拟 DB 返回新行 (L2 之后的新增)
        new_rows = _make_rows(["http://x.com/delta1"], prefix="[DELTA]")
        with patch("app.database.db.Database") as MockDB:
            mock_db_instance = MockDB.return_value
            mock_db_instance.delta_load_since.return_value = new_rows

            projects, total, source = self.cache.get_main()

        self.assertIn(source, ("l1+delta", "l2+delta"))  # delta 后从 L1 返回
        self.assertEqual(total, 51)  # 50 from L2 + 1 new


if __name__ == "__main__":
    unittest.main()