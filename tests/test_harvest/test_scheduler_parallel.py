"""Test SmartScheduler parallel execution (P0 fix for 2026-06-08 Bug 1).

Bug 1: schedule() 之前是单 coroutine 串行, 22s/task, 300 task 要 110 分钟
修复: 启动 max_concurrent 个 worker 协程, 真正并行
"""
import asyncio
import time
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from app.core.harvest.smart_scheduler import SmartScheduler, CrawlTask, TaskStatus


def make_task(task_id: str, source: str = "test", delay: float = 0.5) -> CrawlTask:
    return CrawlTask(
        task_id=task_id,
        source=source,
        url=f"http://test/{task_id}",
        info_type="招标公告",
    )


async def test_parallel_execution():
    """5 并发, 10 task, 每个 1s → 总耗时应 < 2s (vs 串行 10s)"""
    scheduler = SmartScheduler(max_concurrent=5)
    tasks = [make_task(f"t{i}") for i in range(10)]

    async def slow_crawler(task: CrawlTask) -> bool:
        await asyncio.sleep(1.0)
        return True

    for t in tasks:
        await scheduler.register(t)

    t0 = time.monotonic()
    results = await scheduler.schedule(slow_crawler)
    elapsed = time.monotonic() - t0

    assert results["succeeded"] == 10, f"expected 10 succeeded, got {results}"
    # 10 task / 5 worker = 2 batches × 1s = ~2s
    assert elapsed < 3.5, f"parallel not working: elapsed={elapsed:.2f}s, expected <3.5s"
    print(f"✅ test_parallel_execution: 10 task × 1s / 5 worker = {elapsed:.2f}s")


async def test_max_requeue_limit():
    """同一 task 反复 requeue 应被丢弃 (避免死循环)"""
    scheduler = SmartScheduler(max_concurrent=1)
    task = make_task("t0")
    await scheduler.register(task)

    call_count = 0

    async def fail_crawler(task: CrawlTask) -> bool:
        nonlocal call_count
        call_count += 1
        return False  # 模拟失败

    # 模拟 should_skip 永远 True (把 _last_used 设为 future)
    scheduler.interval_manager._last_used["test"] = time.time() + 1000

    results = await scheduler.schedule(fail_crawler)
    # 应该被 requeue MAX_REQUEUE=3 次后丢弃
    # call_count = 0 (skip 不调用 crawler), skipped = 1
    assert results["skipped"] == 1, f"expected skipped=1, got {results}"
    print(f"✅ test_max_requeue_limit: skipped={results['skipped']}, call_count={call_count}")


async def test_exit_condition():
    """所有 task 完成后 worker 正确退出 (不挂起)"""
    scheduler = SmartScheduler(max_concurrent=3)
    tasks = [make_task(f"t{i}") for i in range(5)]

    async def quick_crawler(task: CrawlTask) -> bool:
        await asyncio.sleep(0.1)
        return True

    for t in tasks:
        await scheduler.register(t)

    t0 = time.monotonic()
    try:
        results = await asyncio.wait_for(scheduler.schedule(quick_crawler), timeout=5.0)
        elapsed = time.monotonic() - t0
        assert results["succeeded"] == 5
        print(f"✅ test_exit_condition: 5 task / 3 worker = {elapsed:.2f}s, all succeeded")
    except asyncio.TimeoutError:
        print(f"❌ test_exit_condition: workers didn't exit (timeout after 5s)")
        raise


async def test_priority_order():
    """高 priority task 先执行 (heap order)"""
    scheduler = SmartScheduler(max_concurrent=1)  # 单 worker 验证顺序

    high = make_task("high", source="high_src")
    low = make_task("low", source="low_src")
    # register 后 _tasks 才有 task, priority_dynamic 才会被设置
    await scheduler.register(high)
    await scheduler.register(low)
    # 调整 priority_dynamic
    scheduler._tasks["high"].priority_dynamic = 0.9
    scheduler._tasks["low"].priority_dynamic = 0.3

    execution_order = []

    async def record_crawler(task: CrawlTask) -> bool:
        execution_order.append(task.task_id)
        return True

    # 清空 register 入队的, 重新按 priority 顺序入队
    while not scheduler._queue.empty():
        await scheduler._queue.get()
        scheduler._queue.task_done()
    await scheduler._queue.put((-0.3, "low"))
    await scheduler._queue.put((-0.9, "high"))

    await scheduler.schedule(record_crawler)

    # PriorityQueue min-heap, -0.9 < -0.3, so "high" pops first
    assert execution_order == ["high", "low"], f"expected ['high', 'low'], got {execution_order}"
    print(f"✅ test_priority_order: {execution_order}")


async def main():
    print("=" * 60)
    print("SmartScheduler 并行化测试 (P0 修复验证)")
    print("=" * 60)
    await test_parallel_execution()
    await test_max_requeue_limit()
    await test_exit_condition()
    await test_priority_order()
    print("=" * 60)
    print("✅ 全部通过")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
