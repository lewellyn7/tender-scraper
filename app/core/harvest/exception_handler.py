"""
Phase 1 异常检测与自动恢复状态机
=================================
- AnomalyClassifier: 异常模式分类
- ExceptionStateMachine: 异常状态自动恢复状态机
- RecoveryActions: 恢复策略定义
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger("exception_handler")

# ─────────────────────────────────────────────────────────────────────────────
# 异常类型定义
# ─────────────────────────────────────────────────────────────────────────────


class AnomalyType(Enum):
    RATE_LIMIT = "rate_limit"         # 429 - 频率限制
    BAN = "ban"                       # 403 / IP封禁 / Captcha
    NETWORK_TIMEOUT = "network_timeout"  # 网络超时 / 连接重置
    PARSE_ERROR = "parse_error"       # 选择器失效 / 解析异常
    SERVER_ERROR = "server_error"     # 5xx 服务器错误
    UNKNOWN = "unknown"               # 未知异常


class RecoveryAction(Enum):
    BACKOFF_LONG = "backoff_long"     # 长退避 5-15min
    SWITCH_PROXY = "switch_proxy"      # 切换代理 / 站点
    RETRY_QUICK = "retry_quick"        # 短重试 10-30s
    ADAPT_SELECTOR = "adapt_selector"  # 切换备选选择器
    WAIT_AND_RETRY = "wait_and_retry"  # 等待恢复
    HALT = "halt"                      # 停止并告警


# ─────────────────────────────────────────────────────────────────────────────
# 异常分类器
# ─────────────────────────────────────────────────────────────────────────────


class AnomalyClassifier:
    """
    采集异常分类引擎

    根据错误信号（HTTP状态码 + 错误消息关键词）自动分类异常类型，
    并返回对应的恢复策略和通知标记。
    """

    PATTERNS = {
        AnomalyType.RATE_LIMIT: {
            "signals": ["429", "rate limit", "too many requests", "retry-after"],
            "http_codes": [429],
            "action": RecoveryAction.BACKOFF_LONG,
            "notify": False,
            "severity": "medium",
        },
        AnomalyType.BAN: {
            "signals": [
                "403", "forbidden", "access denied", "ip blocked",
                "captcha", "captcha required", "blocked", "banned",
                "blacklisted", "access denied", "请验证",
            ],
            "http_codes": [403, 451],
            "action": RecoveryAction.SWITCH_PROXY,
            "notify": True,
            "severity": "critical",
        },
        AnomalyType.NETWORK_TIMEOUT: {
            "signals": [
                "timeout", "timed out", "connection reset",
                "network unreachable", "no route to host",
                "connection refused", "temporary failure",
                "ECONNREFUSED", "ETIMEDOUT", "ENETUNREACH",
            ],
            "http_codes": [],
            "action": RecoveryAction.RETRY_QUICK,
            "notify": False,
            "severity": "low",
        },
        AnomalyType.PARSE_ERROR: {
            "signals": [
                "selector", "mismatch", "null field", "parse exception",
                "no element found", "element not found", "attributeerror",
                "indexerror", "keyerror", "noneType",
                "解析失败", "选择器错误", "字段为空",
            ],
            "http_codes": [],
            "action": RecoveryAction.ADAPT_SELECTOR,
            "notify": True,
            "severity": "medium",
        },
        AnomalyType.SERVER_ERROR: {
            "signals": [
                "500", "502", "503", "504",
                "internal server error", "bad gateway",
                "service unavailable", "gateway timeout",
            ],
            "http_codes": [500, 502, 503, 504],
            "action": RecoveryAction.WAIT_AND_RETRY,
            "notify": False,
            "severity": "medium",
        },
    }

    # 备选选择器列表（按优先级）
    FALLBACK_SELECTORS = [
        "article.list-item",
        "div.news-item",
        "table.result-list tr",
        ".tender-item",
        "#content .list",
    ]

    def __init__(self):
        self._classification_cache: dict[str, AnomalyType] = {}
        self._stats: defaultdict[AnomalyType, int] = defaultdict(int)

    def classify(
        self, error: Exception, context: Optional[dict] = None
    ) -> AnomalyResult:
        """
        异常分类

        Args:
            error: 捕获的异常
            context: 额外上下文（HTTP状态码、URL、响应内容等）

        Returns:
            AnomalyResult: 包含类型、恢复策略、通知标记、建议
        """
        context = context or {}
        msg = str(error).lower()
        status = context.get("http_status", 0)
        url = context.get("url", "")

        # 检查缓存（避免重复分类开销）
        cache_key = f"{status}:{msg[:50]}"
        if cache_key in self._classification_cache:
            cached_type = self._classification_cache[cache_key]
            return self._build_result(cached_type, context)

        # 按优先级匹配
        for anomaly_type, pattern in self.PATTERNS.items():
            # 关键词匹配
            if any(sig in msg for sig in pattern["signals"]):
                self._classification_cache[cache_key] = anomaly_type
                self._stats[anomaly_type] += 1
                return self._build_result(anomaly_type, context)

            # HTTP状态码匹配
            if status in pattern["http_codes"]:
                self._classification_cache[cache_key] = anomaly_type
                self._stats[anomaly_type] += 1
                return self._build_result(anomaly_type, context)

        # 兜底为 UNKNOWN
        self._classification_cache[cache_key] = AnomalyType.UNKNOWN
        self._stats[AnomalyType.UNKNOWN] += 1
        logger.debug(f"[AnomalyClassifier] 未知异常: {error} | status={status}")
        return self._build_result(AnomalyType.UNKNOWN, context)

    def _build_result(
        self, anomaly_type: AnomalyType, context: dict
    ) -> AnomalyResult:
        pattern = self.PATTERNS.get(anomaly_type)
        if pattern is None:
            # UNKNOWN 或未匹配类型
            return AnomalyResult(
                anomaly_type=anomaly_type,
                action=RecoveryAction.RETRY_QUICK,
                notify=False,
                severity="low",
                context=context,
            )
        return AnomalyResult(
            anomaly_type=anomaly_type,
            action=pattern["action"],
            notify=pattern["notify"],
            severity=pattern["severity"],
            context=context,
        )

    @property
    def stats(self) -> dict:
        return {k.value: v for k, v in self._stats.items()}


@dataclass
class AnomalyResult:
    """分类结果"""

    anomaly_type: AnomalyType
    action: RecoveryAction
    notify: bool
    severity: str  # critical / medium / low
    context: dict


# ─────────────────────────────────────────────────────────────────────────────
# 恢复策略执行器
# ─────────────────────────────────────────────────────────────────────────────


class RecoveryExecutor:
    """
    恢复策略执行器

    根据异常类型执行对应恢复动作：
    - BACKOFF_LONG: 更新调度器长退避时间
    - SWITCH_PROXY: 切换代理（需要外部代理池）
    - RETRY_QUICK: 快速重试
    - ADAPT_SELECTOR: 切换备选选择器
    - WAIT_AND_RETRY: 等待后重试
    - HALT: 停止任务并告警
    """

    # 退避时间配置（秒）
    BACKOFF_CONFIG = {
        RecoveryAction.BACKOFF_LONG: (300, 900),   # 5-15 分钟
        RecoveryAction.RETRY_QUICK: (10, 30),       # 10-30 秒
        RecoveryAction.WAIT_AND_RETRY: (60, 180),   # 1-3 分钟
    }

    def __init__(
        self,
        scheduler: Optional["SmartScheduler"] = None,
        proxy_manager: Optional[Callable[[], str]] = None,
    ):
        self.scheduler = scheduler
        self.proxy_manager = proxy_manager  # () -> str
        self._retry_delays: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=10)
        )  # 记录近期延迟，检测震荡

    async def execute(
        self,
        result: AnomalyResult,
        task_id: str,
        source: str,
    ) -> RecoveryDecision:
        """
        执行恢复策略

        Returns:
            RecoveryDecision: 包含执行的动作、延迟时间、是否继续重试
        """
        action = result.action
        task_key = f"{source}:{task_id}"

        if action == RecoveryAction.HALT:
            return RecoveryDecision(
                action=action,
                delay_seconds=0,
                should_retry=False,
                should_notify=True,
                message=f"严重异常，任务 {task_id} 已停止",
            )

        if action == RecoveryAction.SWITCH_PROXY:
            proxy = self._get_alternate_proxy()
            return RecoveryDecision(
                action=action,
                delay_seconds=5,
                should_retry=True,
                should_notify=result.notify,
                message=f"切换代理: {proxy}",
                extra={"proxy": proxy},
            )

        if action in self.BACKOFF_CONFIG:
            delay = self._compute_delay(action, task_key)
            self._retry_delays[task_key].append(delay)

            # 震荡检测：连续3次退避时间相近 → 疑似死循环
            if self._detect_oscillation(task_key):
                logger.warning(
                    f"[RecoveryExecutor] 任务 {task_id} 疑似震荡，停止重试"
                )
                return RecoveryDecision(
                    action=action,
                    delay_seconds=0,
                    should_retry=False,
                    should_notify=True,
                    message=f"检测到重试震荡，任务 {task_id} 已停止",
                )

            return RecoveryDecision(
                action=action,
                delay_seconds=delay,
                should_retry=True,
                should_notify=result.notify,
                message=f"退避 {delay:.0f}s 后重试",
            )

        if action == RecoveryAction.ADAPT_SELECTOR:
            selector = self._get_alternate_selector(source)
            return RecoveryDecision(
                action=action,
                delay_seconds=2,
                should_retry=True,
                should_notify=result.notify,
                message=f"切换选择器: {selector}",
                extra={"selector": selector, "source": source},
            )

        # WAIT_AND_RETRY / 默认
        return RecoveryDecision(
            action=action,
            delay_seconds=30,
            should_retry=True,
            should_notify=False,
            message="等待后重试",
        )

    def _compute_delay(self, action: RecoveryAction, task_key: str) -> float:
        """计算带抖动的退避时间"""
        min_d, max_d = self.BACKOFF_CONFIG[action]
        base = random.uniform(min_d, max_d)

        # 震荡惩罚：近期重试次数越多，退避越长
        retry_count = len(self._retry_delays[task_key])
        if retry_count > 0:
            jitter = random.uniform(0.8, 1.2)
            base *= min(3.0, 1 + retry_count * 0.2)  # 最多延长3倍
            base *= jitter

        return base

    def _detect_oscillation(self, task_key: str) -> bool:
        """震荡检测：连续3次延迟差值 < 20%"""
        delays = list(self._retry_delays[task_key])
        if len(delays) < 3:
            return False

        recent = delays[-3:]
        avg = sum(recent) / 3
        variance = sum((d - avg) ** 2 for d in recent) / 3
        cv = (variance ** 0.5) / avg if avg > 0 else 1.0
        return cv < 0.2  # 变异系数 < 20% 视为震荡

    def _get_alternate_proxy(self) -> str:
        """获取备用代理（外部代理池接口）"""
        if self.proxy_manager:
            return self.proxy_manager()
        # 无代理管理器，返回占位符
        return "proxy_unavailable"

    def _get_alternate_selector(self, source: str) -> str:
        """获取备选选择器（轮换）"""
        idx = hash(source) % len(AnomalyClassifier.FALLBACK_SELECTORS)
        return AnomalyClassifier.FALLBACK_SELECTORS[idx]


@dataclass
class RecoveryDecision:
    """恢复决策"""

    action: RecoveryAction
    delay_seconds: float
    should_retry: bool
    should_notify: bool
    message: str
    extra: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# 异常状态机
# ─────────────────────────────────────────────────────────────────────────────


class ExceptionStateMachine:
    """
    异常状态自动恢复状态机

    状态流转:
      IDLE → RUNNING → CLASSIFY_ANOMALY → EXECUTE_RECOVERY
                                        ↓ (可恢复)
                                  AUTOMATED_HEAL → RUNNING
                                        ↓ (不可恢复)
                                        HALT

    特性:
    - 异常分类（AnomalyClassifier）
    - 策略执行（RecoveryExecutor）
    - 震荡检测（防止死循环）
    - 告警触发（notify）
    """

    MAX_RETRIES_PER_SOURCE = 10  # 单站点最大连续重试次数

    def __init__(
        self,
        scheduler: Optional["SmartScheduler"] = None,
        proxy_manager: Optional[Callable[[], str]] = None,
        notifier: Optional[Callable[[str, AnomalyResult, RecoveryDecision], None]] = None,
    ):
        self.classifier = AnomalyClassifier()
        self.executor = RecoveryExecutor(scheduler, proxy_manager)
        self.notifier = notifier  # (title, result, decision) -> None

        # 状态追踪
        self._state: dict[str, str] = defaultdict(lambda: "IDLE")
        self._retry_counts: defaultdict[str, int] = defaultdict(int)
        self._history: dict[str, list] = defaultdict(list)

    @property
    def state(self) -> dict[str, str]:
        return dict(self._state)

    async def handle_exception(
        self,
        task_id: str,
        source: str,
        error: Exception,
        context: Optional[dict] = None,
    ) -> RecoveryDecision:
        """
        核心入口：处理异常，返回恢复决策

        Args:
            task_id: 任务ID
            source: 站点标识
            error: 捕获的异常
            context: 额外上下文

        Returns:
            RecoveryDecision: 是否重试、延迟多久、是否告警
        """
        key = f"{source}:{task_id}"
        self._state[key] = "CLASSIFY_ANOMALY"

        # Step 1: 分类
        result = self.classifier.classify(error, context)
        self._state[key] = "EXECUTE_RECOVERY"

        # 记录历史
        self._history[key].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": result.anomaly_type.value,
            "action": result.action.value,
            "severity": result.severity,
        })
        if len(self._history[key]) > 50:
            self._history[key] = self._history[key][-50:]

        # 检查重试上限
        self._retry_counts[key] += 1
        if self._retry_counts[key] > self.MAX_RETRIES_PER_SOURCE:
            logger.error(
                f"[ExceptionStateMachine] 任务 {task_id} 超过最大重试次数"
            )
            decision = RecoveryDecision(
                action=RecoveryAction.HALT,
                delay_seconds=0,
                should_retry=False,
                should_notify=True,
                message=f"超过最大重试次数 {self.MAX_RETRIES_PER_SOURCE}",
            )
            self._state[key] = "HALT"
            self._maybe_notify(task_id, result, decision)
            return decision

        # Step 2: 执行恢复策略
        decision = await self.executor.execute(result, task_id, source)

        if decision.should_retry:
            self._state[key] = "AUTOMATED_HEAL"
        else:
            self._state[key] = "HALT"

        # Step 3: 告警
        if decision.should_notify:
            self._maybe_notify(task_id, result, decision)

        logger.info(
            f"[ExceptionStateMachine] {source}:{task_id} → "
            f"{result.anomaly_type.value} | {decision.message}"
        )
        return decision

    def reset_task(self, task_id: str, source: str):
        """重置任务状态（任务成功完成后调用）"""
        key = f"{source}:{task_id}"
        self._state[key] = "IDLE"
        self._retry_counts[key] = 0

    def get_task_history(self, task_id: str, source: str) -> list:
        """获取任务异常历史"""
        return list(self._history.get(f"{source}:{task_id}", []))

    def _maybe_notify(
        self, task_id: str, result: AnomalyResult, decision: RecoveryDecision
    ):
        """发送通知（如果配置了notifier）"""
        if self.notifier:
            title = f"采集异常 [{result.anomaly_type.value}] {task_id}"
            self.notifier(title, result, decision)

    @property
    def stats(self) -> dict:
        """统计信息"""
        return {
            "current_states": dict(self._state),
            "retry_counts": dict(self._retry_counts),
            "classification_stats": self.classifier.stats,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 与调度器集成适配器
# ─────────────────────────────────────────────────────────────────────────────


class SchedulerExceptionHandler:
    """
    将 ExceptionStateMachine 嵌入 SmartScheduler 的适配层

    用法:
        handler = SchedulerExceptionHandler(scheduler)
        scheduler = handler.wrap(scheduler)
    """

    def __init__(self, scheduler: "SmartScheduler"):
        self.scheduler = scheduler
        self.state_machine = ExceptionStateMachine(scheduler=scheduler)

    async def handle_crawl_exception(
        self, task: "CrawlTask", error: Exception, context: dict
    ) -> tuple[bool, float]:
        """
        处理采集异常

        Returns:
            (should_retry, retry_delay_seconds)
        """
        decision = await self.state_machine.handle_exception(
            task_id=task.task_id,
            source=task.source,
            error=error,
            context=context,
        )

        if decision.should_retry:
            # 将异常记录到调度器
            self.scheduler.priority_engine.record_failure(task.source)
            return True, decision.delay_seconds
        else:
            return False, 0.0

    def wrap_crawler(self, crawler_fn) -> Callable:
        """
        包装原始 crawler 函数，自动异常处理

        Usage:
            wrapped_crawler = handler.wrap_crawler(original_crawler)
            await scheduler.schedule(wrapped_crawler)
        """

        async def wrapped(task: "CrawlTask") -> bool:
            try:
                return await crawler_fn(task)
            except Exception as e:
                context = {"url": task.url, "source": task.source}
                should_retry, delay = await self.handle_crawl_exception(
                    task, e, context
                )
                if should_retry:
                    task.retry_count += 1
                    # 延迟后重新入队
                    await asyncio.sleep(delay)
                    await self.scheduler.register(task)
                    return False
                else:
                    return False

        return wrapped


# ─────────────────────────────────────────────────────────────────────────────
# 示例 / 测试
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import random

    logging.basicConfig(level=logging.INFO)

    async def demo():
        # 模拟不同类型的异常
        exceptions = [
            (Exception("HTTP 429: rate limit exceeded"), {"http_status": 429}),
            (Exception("403 Forbidden: IP blocked"), {"http_status": 403}),
            (Exception("asyncio.TimeoutError: timeout"), {}),
            (Exception("Selector match failed: .news-item not found"), {}),
            (Exception("HTTP 503: Service Unavailable"), {"http_status": 503}),
            (Exception("Unknown error"), {}),
        ]

        classifier = AnomalyClassifier()
        executor = RecoveryExecutor()
        sm = ExceptionStateMachine()

        print("\n=== 异常分类测试 ===")
        for exc, ctx in exceptions:
            result = classifier.classify(exc, ctx)
            decision = await executor.execute(result, task_id="test_1", source="cqggzy")
            print(
                f"  {exc.__class__.__name__}: {exc}\n"
                f"    → {result.anomaly_type.value} | "
                f"{result.severity} | {result.action.value}\n"
                f"    → {decision.message} (retry={decision.should_retry})"
            )

        print(f"\n分类统计: {classifier.stats}")

        print("\n=== 状态机流转测试 ===")
        for i in range(3):
            exc = Exception("rate limit exceeded")
            ctx = {"http_status": 429, "url": "http://example.com"}
            decision = await sm.handle_exception(
                task_id=f"task_{i}", source="cqggzy", error=exc, context=ctx
            )
            print(f"  尝试 {i+1}: {decision.message}")

        print(f"\n任务状态: {sm.state}")
        print(f"重试计数: {dict(sm._retry_counts)}")

        print("\n=== 震荡检测测试 ===")
        for i in range(5):
            exc = Exception("429 rate limit")
            decision = await sm.handle_exception(
                task_id="osc_task", source="test_source", error=exc, context={"http_status": 429}
            )
            print(f"  尝试 {i+1}: {decision.message}")

    asyncio.run(demo())
