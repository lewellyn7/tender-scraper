"""
Phase 1 智能调度核心
====================
- DynamicPriorityEngine: 5因子动态优先级引擎
- AdaptiveIntervalManager: 自适应采集间隔
- CrawlTask: 任务数据结构
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import numpy as np

logger = logging.getLogger("smart_scheduler")

# ─────────────────────────────────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────────────────────────────────


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class CrawlTask:
    """采集任务"""

    task_id: str
    source: str  # 站点标识，如 "cqggzy", "ccgp"
    url: str
    info_type: str = "招标公告"  # 招标公告 / 中标结果 / 采购意向
    region: str = "重庆"
    deadline: Optional[datetime] = None  # 招标截止时间
    keywords: list[str] = field(default_factory=list)  # 关键词匹配
    priority_static: int = 5  # 静态优先级 1-10

    # 运行时字段（会被动态优先级覆盖）
    status: TaskStatus = TaskStatus.PENDING
    priority_dynamic: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    error: Optional[str] = None


@dataclass
class SourceMetrics:
    """站点度量数据"""

    source: str
    response_times_ms: deque = field(default_factory=lambda: deque(maxlen=100))
    success_records: deque = field(default_factory=lambda: deque(maxlen=50))  # [bool]
    error_counts: defaultdict = field(default_factory=lambda: defaultdict(int))
    last_success_at: Optional[datetime] = None
    last_error_at: Optional[datetime] = None
    ban_until: Optional[datetime] = None  # 被封禁直到

    @property
    def success_rate(self) -> float:
        if not self.success_records:
            return 0.85  # 默认
        return sum(self.success_records) / len(self.success_records)

    @property
    def avg_response_time_ms(self) -> float:
        if not self.response_times_ms:
            return 2000.0  # 默认 2s
        return float(np.mean(self.response_times_ms))

    @property
    def is_banned(self) -> bool:
        if self.ban_until is None:
            return False
        return datetime.now(timezone.utc) < self.ban_until


# ─────────────────────────────────────────────────────────────────────────────
# 动态优先级引擎
# ─────────────────────────────────────────────────────────────────────────────


class DynamicPriorityEngine:
    """
    5因子动态优先级计算

    公式:
        priority_score = w1×时效性 + w2×来源可靠性 + w3×采集成本
                       + w4×历史成功率 + w5×用户需求强度
    """

    DEFAULT_WEIGHTS = {
        "timeliness": 0.25,
        "reliability": 0.20,
        "cost": 0.15,
        "success_rate": 0.20,
        "demand": 0.20,
    }

    def __init__(
        self,
        weights: Optional[dict[str, float]] = None,
        demand_tracker: Optional[DemandTracker] = None,
    ):
        self.weights = {**self.DEFAULT_WEIGHTS, **(weights or {})}
        # 归一化权重
        total = sum(self.weights.values())
        self.weights = {k: v / total for k, v in self.weights.items()}

        self.demand_tracker = demand_tracker or DemandTracker()
        self._source_metrics: dict[str, SourceMetrics] = {}
        self._cost_estimator = CostEstimator()

    def get_or_create_metrics(self, source: str) -> SourceMetrics:
        if source not in self._source_metrics:
            self._source_metrics[source] = SourceMetrics(source=source)
        return self._source_metrics[source]

    async def compute_priority(self, task: CrawlTask) -> float:
        """计算动态优先级分数 [0, 1]"""
        metrics = self.get_or_create_metrics(task.source)

        t = await self._timeliness_factor(task)
        r = await self._reliability_factor(task, metrics)
        c = await self._cost_factor(task, metrics)
        s = await self._success_rate_factor(task, metrics)
        d = await self._demand_factor(task)

        score = (
            self.weights["timeliness"] * t
            + self.weights["reliability"] * r
            + self.weights["cost"] * c
            + self.weights["success_rate"] * s
            + self.weights["demand"] * d
        )

        task.priority_dynamic = score
        return score

    async def _timeliness_factor(self, task: CrawlTask) -> float:
        """
        时效性因子：招标截止前 48h 权重指数上升
        0 (已过期) → 1 (48h 后)
        """
        if task.deadline is None:
            return 0.5  # 无截止时间，取中间值

        now = datetime.now(timezone.utc)
        if task.deadline.tzinfo is None:
            task.deadline = task.deadline.replace(tzinfo=timezone.utc)

        hours_left = (task.deadline - now).total_seconds() / 3600

        if hours_left <= 0:
            return 1.0  # 已过期，优先处理
        if hours_left > 168:  # > 7 天，略降低
            return 0.3

        # 渐变上升曲线：1 - exp(-hours_left / 48)
        return 1.0 - math.exp(-hours_left / 48)

    async def _reliability_factor(self, task: CrawlTask, metrics: SourceMetrics) -> float:
        """
        来源可靠性：站点可用性历史滑动均值
        """
        if metrics.is_banned:
            return 0.0

        avg_rt = metrics.avg_response_time_ms
        # 响应时间越短，可靠性越高（归一化到 0-1）
        # 基准 5000ms → 0.5，500ms → 1.0，>10000ms → 0
        reliability = max(0.0, min(1.0, (10000 - avg_rt) / 9500))
        return reliability

    async def _cost_factor(self, task: CrawlTask, metrics: SourceMetrics) -> float:
        """
        采集成本：归一化预估耗时（越小越优先）
        """
        estimated_ms = self._cost_estimator.estimate(task, metrics)
        # 归一化：500ms → 1.0，30000ms → 0
        cost = max(0.0, min(1.0, (30000 - estimated_ms) / 29500))
        return cost

    async def _success_rate_factor(self, task: CrawlTask, metrics: SourceMetrics) -> float:
        """
        历史成功率：近 7 天滑动平均
        """
        return metrics.success_rate

    async def _demand_factor(self, task: CrawlTask) -> float:
        """
        用户需求强度：查询频率
        """
        demand_score = self.demand_tracker.get_demand(task.source, task.keywords)
        # 归一化 [0, 1]
        return min(1.0, demand_score / 10.0)

    # ── 反馈更新 ─────────────────────────────────────────────────────────────

    def record_success(self, source: str, response_time_ms: float):
        """记录成功采集"""
        metrics = self.get_or_create_metrics(source)
        metrics.response_times_ms.append(response_time_ms)
        metrics.success_records.append(True)
        metrics.last_success_at = datetime.now(timezone.utc)

    def record_failure(self, source: str, response_time_ms: Optional[float] = None):
        """记录失败"""
        metrics = self.get_or_create_metrics(source)
        if response_time_ms is not None:
            metrics.response_times_ms.append(response_time_ms)
        metrics.success_records.append(False)
        metrics.last_error_at = datetime.now(timezone.utc)

    def record_error_type(self, source: str, error_type: str):
        """记录错误类型计数"""
        metrics = self.get_or_create_metrics(source)
        metrics.error_counts[error_type] += 1


class CostEstimator:
    """采集成本估算器"""

    # 各类任务的基准耗时（毫秒）
    BASE_COSTS = {
        "招标公告": 3000,
        "中标结果": 2500,
        "采购意向": 2000,
        "default": 3000,
    }

    def estimate(self, task: CrawlTask, metrics: SourceMetrics) -> float:
        base = self.BASE_COSTS.get(task.info_type, self.BASE_COSTS["default"])
        # 动态调整：响应波动大 → 提高成本估算
        if len(metrics.response_times_ms) >= 10:
            cv = np.std(metrics.response_times_ms) / np.mean(metrics.response_times_ms)
            base *= 1 + cv
        return base


class DemandTracker:
    """
    用户需求强度追踪
    实际生产中应接 Redis 或数据库，简化使用内存 deque
    """

    def __init__(self):
        # {source: deque([timestamp, ...])}
        self._source_queries: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        self._keyword_queries: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        self._window_seconds = 3600  # 1小时窗口

    def record_query(self, source: str, keywords: list[str]):
        now = time.time()
        self._source_queries[source].append(now)
        for kw in keywords:
            self._keyword_queries[kw.lower()].append(now)

    def get_demand(self, source: str, keywords: list[str]) -> float:
        now = time.time()
        window = self._window_seconds

        source_count = sum(1 for t in self._source_queries[source] if now - t < window)
        kw_count = 0
        for kw in keywords:
            kw_count += sum(1 for t in self._keyword_queries[kw.lower()] if now - t < window)

        return source_count + kw_count * 0.5


# ─────────────────────────────────────────────────────────────────────────────
# 自适应采集间隔管理器
# ─────────────────────────────────────────────────────────────────────────────


class AdaptiveIntervalManager:
    """
    根据站点响应特征自动调整采集间隔

    策略：
    - 响应稳定（CV低）→ 缩小间隔，提高采集密度
    - 响应波动大（CV高）→ 扩大间隔，保护站点
    - 错误率高 → 大幅延长间隔
    """

    MIN_INTERVAL = 10.0  # 秒（避免触发网站反爬限制）
    MAX_INTERVAL = 60.0  # 秒
    CRITICAL_INTERVAL = 300.0  # 被ban后恢复检查间隔

    def __init__(self, priority_engine: DynamicPriorityEngine):
        self.priority_engine = priority_engine
        # 每个站点的响应时间记录
        self._intervals: dict[str, float] = defaultdict(lambda: 2.0)  # 默认 2s
        self._last_used: dict[str, float] = defaultdict(time.time)

    async def get_interval(self, task: CrawlTask) -> float:
        """
        计算下次采集该站点的推荐间隔（秒）
        """
        metrics = self.priority_engine.get_or_create_metrics(task.source)

        # 被ban状态：使用超长间隔
        if metrics.is_banned:
            remaining = (metrics.ban_until - datetime.now(timezone.utc)).total_seconds()
            return max(self.CRITICAL_INTERVAL, remaining)

        recent = list(metrics.response_times_ms)[-20:]
        if not recent:
            return self._intervals[task.source]

        avg_rt = float(np.mean(recent))
        std_rt = float(np.std(recent))

        # 变异系数（CV）：波动程度
        cv = std_rt / avg_rt if avg_rt > 0 else 1.0

        # 基础间隔 = 平均响应时间（毫秒→秒）
        base = avg_rt / 1000.0

        # 波动系数放大
        interval = base * (1 + cv)

        # 错误率惩罚
        error_rate = 1.0 - metrics.success_rate
        if error_rate > 0.1:
            interval *= 1 + error_rate * 5  # 错误率高则大幅延长

        # 夹紧到 [MIN, MAX]
        clamped = max(self.MIN_INTERVAL, min(interval, self.MAX_INTERVAL))
        self._intervals[task.source] = clamped
        return clamped

    async def should_skip(self, task: CrawlTask) -> bool:
        """
        判断是否应跳过本次采集（频繁访问）
        """
        source = task.source
        now = time.time()
        last = self._last_used.get(source, 0)
        interval = self._intervals[source]

        if now - last < interval:
            return True
        self._last_used[source] = now
        return False

    def record_actual_interval(self, source: str, actual_ms: float):
        """
        记录实际采集耗时，用于校准间隔估算
        """
        metrics = self.priority_engine.get_or_create_metrics(source)
        metrics.response_times_ms.append(actual_ms)

    def apply_ban(self, source: str, duration_seconds: int = 300):
        """
        应用临时封禁
        """
        metrics = self.priority_engine.get_or_create_metrics(source)
        ban_until = datetime.now(timezone.utc).replace(
            tzinfo=timezone.utc
        ).__add__(duration_seconds)
        metrics.ban_until = ban_until
        logger.warning(f"[AdaptiveInterval] 站点 {source} 被封禁 {duration_seconds}s")


# ─────────────────────────────────────────────────────────────────────────────
# 智能调度器（整合）
# ─────────────────────────────────────────────────────────────────────────────


class SmartScheduler:
    """
    Phase 1 智能调度器

    整合动态优先级引擎 + 自适应间隔管理器，
    持 asyncio PriorityQueue 作为调度核心。
    """

    def __init__(self, max_concurrent: int = 10):
        self.max_concurrent = max_concurrent
        self.priority_engine = DynamicPriorityEngine()
        self.interval_manager = AdaptiveIntervalManager(self.priority_engine)
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._running: set[str] = set()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: dict[str, CrawlTask] = {}

        logger.info(f"[SmartScheduler] 初始化，最大并发 {max_concurrent}")

    # ── 任务注册 ─────────────────────────────────────────────────────────────

    async def register(self, task: CrawlTask) -> float:
        """注册任务，返回动态优先级分数"""
        priority = await self.priority_engine.compute_priority(task)
        self._tasks[task.task_id] = task
        await self._queue.put((priority, task.task_id))
        logger.debug(
            f"[SmartScheduler] 注册任务 {task.task_id}，优先级 {priority:.4f}"
        )
        return priority

    async def register_batch(self, tasks: list[CrawlTask]) -> list[float]:
        """批量注册"""
        priorities = []
        for t in tasks:
            p = await self.priority_engine.compute_priority(t)
            priorities.append(p)
        # 按优先级排序入队（高优先级先处理）
        sorted_tasks = sorted(zip(priorities, tasks), key=lambda x: -x[0])
        for priority, task in sorted_tasks:
            self._tasks[task.task_id] = task
            await self._queue.put((priority, task.task_id))
        return priorities

    # ── 调度循环 ─────────────────────────────────────────────────────────────

    async def schedule(self, crawler_fn) -> dict:
        """
        调度循环：持续从队列取任务执行
        crawler_fn: async def(task: CrawlTask) -> bool  返回是否成功
        """
        results = {"succeeded": 0, "failed": 0, "skipped": 0}

        while not self._queue.empty():
            # 取最高优先级任务
            _, task_id = await self._queue.get()
            task = self._tasks.get(task_id)
            if task is None:
                continue

            # 检查是否应跳过（间隔保护）
            if await self.interval_manager.should_skip(task):
                results["skipped"] += 1
                logger.debug(f"[SmartScheduler] 跳过任务 {task_id}（间隔保护），重新入队")
                # 重新入队（稍后重试，不丢弃）
                await self._queue.put((task.priority_dynamic, task_id))
                await asyncio.sleep(0.1)
                continue

            # 并发控制
            async with self._semaphore:
                self._running.add(task_id)
                task.status = TaskStatus.RUNNING
                task.started_at = datetime.now(timezone.utc)

                try:
                    success = await asyncio.wait_for(
                        crawler_fn(task), timeout=60.0
                    )
                    if success:
                        results["succeeded"] += 1
                        task.status = TaskStatus.SUCCEEDED
                        elapsed_ms = (
                            (datetime.now(timezone.utc) - task.started_at).total_seconds()
                            * 1000
                        )
                        self.priority_engine.record_success(task.source, elapsed_ms)
                        self.interval_manager.record_actual_interval(task.source, elapsed_ms)
                    else:
                        results["failed"] += 1
                        task.status = TaskStatus.FAILED
                        self.priority_engine.record_failure(task.source)
                except asyncio.TimeoutError:
                    results["failed"] += 1
                    task.status = TaskStatus.FAILED
                    task.error = "timeout"
                    self.priority_engine.record_failure(task.source, 60000)
                    logger.warning(f"[SmartScheduler] 任务 {task_id} 超时")
                except Exception as e:
                    results["failed"] += 1
                    task.status = TaskStatus.FAILED
                    task.error = str(e)
                    self.priority_engine.record_failure(task.source)
                    logger.error(f"[SmartScheduler] 任务 {task_id} 异常: {e}")
                finally:
                    task.finished_at = datetime.now(timezone.utc)
                    self._running.discard(task_id)
                    self._queue.task_done()

        return results

    # ── 指标导出 ─────────────────────────────────────────────────────────────

    def get_source_stats(self) -> dict:
        """获取各站点统计"""
        stats = {}
        for source, metrics in self.priority_engine._source_metrics.items():
            stats[source] = {
                "success_rate": round(metrics.success_rate, 4),
                "avg_response_ms": round(metrics.avg_response_time_ms, 2),
                "is_banned": metrics.is_banned,
                "ban_until": metrics.ban_until.isoformat() if metrics.ban_until else None,
                "error_counts": dict(metrics.error_counts),
            }
        return stats

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def running_count(self) -> int:
        return len(self._running)


# ─────────────────────────────────────────────────────────────────────────────
# 示例 / 测试
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import random

    logging.basicConfig(level=logging.DEBUG)

    async def demo():
        scheduler = SmartScheduler(max_concurrent=5)

        # 模拟任务
        tasks = []
        for i in range(10):
            deadline = datetime.now(timezone.utc)
            if i % 3 == 0:
                deadline = deadline.replace(hour=deadline.hour + 1)  # 1小时后截止
            else:
                deadline = deadline.replace(day=deadline.day + 3)  # 3天后

            task = CrawlTask(
                task_id=f"task_{i}",
                source=["cqggzy", "ccgp"][i % 2],
                url=f"http://example.com/{i}",
                info_type=["招标公告", "中标结果", "采购意向"][i % 3],
                region="重庆",
                deadline=deadline,
                keywords=["智慧城市", "数字化"] if i % 2 == 0 else [],
            )
            tasks.append(task)

        priorities = await scheduler.register_batch(tasks)
        print(f"\n注册 {len(tasks)} 个任务，优先级范围: {min(priorities):.4f} ~ {max(priorities):.4f}")

        # 模拟采集
        async def dummy_crawler(task: CrawlTask) -> bool:
            await asyncio.sleep(0.1)
            return random.random() > 0.2

        results = await scheduler.schedule(dummy_crawler)
        print(f"\n采集结果: {results}")
        print(f"\n站点统计: {scheduler.get_source_stats()}")

        # 测试自适应间隔
        engine = DynamicPriorityEngine()
        interval_mgr = AdaptiveIntervalManager(engine)

        test_task = CrawlTask(
            task_id="test_interval",
            source="cqggzy",
            url="http://example.com",
        )

        # 模拟几次响应
        for rt in [500, 450, 600, 400, 550]:
            engine.record_success("cqggzy", rt)

        interval = await interval_mgr.get_interval(test_task)
        print(f"\n当前推荐采集间隔: {interval:.2f}s")

    asyncio.run(demo())
