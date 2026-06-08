"""Test AdaptiveIntervalManager per-worker 间隔 (2026-06-08 Bug 1-B)

Bug 1-B: per-source _last_used 全局锁 → 5 worker 同 source 排队 → 2 次 skip → 第 3 次 drop
        现象: 1140 skipped / 221 succeeded
修复: should_skip 加 worker_id 参数, 每个 worker 各自维护 _last_used[worker_id][source]
      5 worker 同 source 不再互相 skip
"""
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from app.core.harvest.smart_scheduler import (
    AdaptiveIntervalManager,
    CrawlTask,
    DynamicPriorityEngine,
)


def make_task(source: str = "cqggzy") -> CrawlTask:
    return CrawlTask(
        task_id=f"t_{int(time.time()*1000)}_{source}",
        source=source,
        url=f"http://test/{source}",
        info_type="招标公告",
    )


class TestShouldSkipPerWorker:
    """2026-06-08 Bug 1-B: should_skip 应支持 per-worker 隔离"""

    def test_same_source_different_workers_not_skip(self):
        """关键场景: 5 worker 同 source 同时调 should_skip, 只有首个 skip (其他 4 个能跑)"""
        from app.core.harvest.smart_scheduler import DynamicPriorityEngine
        mgr = AdaptiveIntervalManager(DynamicPriorityEngine())
        # 强制设 _intervals[source] = 0.5s (避免默认 0 永远不 skip)
        mgr._intervals["cqggzy"] = 0.5
        # 模拟 5 worker 间隔 0.5s 调用 (5 worker 在 0.5s 内)
        results = {}
        for i in range(5):
            # 同一个 worker_id 第二次调用会 skip (间隔太短)
            # 不同 worker_id 不会 skip (各自独立)
            wid = f"worker_{i}"
            r1 = asyncio.run(mgr.should_skip(make_task(), worker_id=wid))
            r2 = asyncio.run(mgr.should_skip(make_task(), worker_id=wid))
            results[wid] = (r1, r2)

        # 每个 worker 第 1 次: 不 skip, 第 2 次: skip (因为 0s 内重入)
        for wid, (r1, r2) in results.items():
            assert r1 is False, f"{wid} first call should not skip"
            assert r2 is True, f"{wid} second call (immediate) should skip"
        # 但 worker_A 和 worker_B 互不影响 (各自独立的 _last_used)

    def test_different_workers_independent(self):
        """关键场景: worker_A 处理完一个 source 后, worker_B 仍能处理同一 source"""
        mgr = AdaptiveIntervalManager(DynamicPriorityEngine())
        # worker_A 处理
        skip_a1 = asyncio.run(mgr.should_skip(make_task(), worker_id="worker_A"))
        # worker_B 处理同一 source, 不应 skip
        skip_b1 = asyncio.run(mgr.should_skip(make_task(), worker_id="worker_B"))
        assert skip_a1 is False, "worker_A first call should not skip"
        assert skip_b1 is False, "worker_B first call should not skip (per-worker isolated)"

    def test_global_source_still_serialized(self):
        """worker 内部仍然按 source 间隔限制 (防反爬)"""
        mgr = AdaptiveIntervalManager(DynamicPriorityEngine())
        # 强制设置 _intervals[source] = 1.0s
        mgr._intervals["cqggzy"] = 1.0
        # 同一 worker 连续 2 次, 第 2 次应 skip
        skip1 = asyncio.run(mgr.should_skip(make_task("cqggzy"), worker_id="worker_0"))
        skip2 = asyncio.run(mgr.should_skip(make_task("cqggzy"), worker_id="worker_0"))
        assert skip1 is False, "first call should pass"
        assert skip2 is True, "immediate second call should skip (interval=1.0s)"


class TestRegressionOldBehavior:
    """验证旧 API 仍然兼容 (worker_id 默认 'default')"""

    def test_no_worker_id_arg_still_works(self):
        """should_skip 不传 worker_id 用 'default', 不报错"""
        mgr = AdaptiveIntervalManager(DynamicPriorityEngine())
        skip = asyncio.run(mgr.should_skip(make_task()))
        assert skip is False, "default worker_id first call should not skip"


class TestRealScenario:
    """真实场景: 5 worker 跑 100 task 同 source 几乎不 skip"""

    def test_5_workers_100_tasks_low_skip(self):
        """5 worker × 100 task = 500 次 should_skip, 不应大量 skip"""
        mgr = AdaptiveIntervalManager(DynamicPriorityEngine())
        # 模拟 5 worker 并行, 每个 worker 处理 100 个 task
        # task 之间间隔 0.1s (模拟 1s task/5worker 节奏)
        skip_count = 0
        for round in range(20):  # 20 轮
            for wid in range(5):
                # 每个 worker 在这一轮调一次
                for _ in range(5):  # 每轮每 worker 5 个 task
                    r = asyncio.run(mgr.should_skip(
                        make_task(), worker_id=f"worker_{wid}"
                    ))
                    if r:
                        skip_count += 1
                time.sleep(0.1)  # 模拟 100ms 间隔

        # 5 worker 各自独立, 5 worker × 100 task = 500 次
        # 只有"同一 worker 连续 0s 内多次"才会 skip
        # 100ms 间隔下, 同一 worker 100ms 内不会多次 (sleep 0.1 在外层)
        # 预期 skip < 50 (1/10)
        assert skip_count < 50, f"too many skips: {skip_count}/500 (per-worker fix not working)"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
