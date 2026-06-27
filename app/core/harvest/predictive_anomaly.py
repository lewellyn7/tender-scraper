"""
Phase 2 异常预测引擎
====================
基于历史时序数据预测站点异常（Ban/限速/服务质量下降），
在异常实际发生前调整调度策略，实现预防性调度。

核心组件:
- AnomalyPredictor: 时序预测器（滑动窗口 + 统计检测）
- TrendAnalyzer: 趋势分析器（成功率/响应时间/错误率）
- PreventiveScheduler: 预防性调度器（预测驱动）
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import numpy as np

logger = logging.getLogger("predictive_anomaly")

# ─────────────────────────────────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────────────────────────────────


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskScore:
    """风险评分"""

    source: str
    risk_level: RiskLevel
    score: float  # [0, 1]
    ban_probability: float  # [0, 1]
    degradation_probability: float  # [0, 1]
    confidence: float  # 预测置信度
    factors: dict  # 风险因子分解
    predicted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    recommendation: str = ""


@dataclass
class SourceHealth:
    """站点健康状态快照"""

    source: str
    success_rate_7d: float  # 7天滑动成功率
    success_rate_1h: float  # 近1小时成功率
    avg_response_time_ms: float
    response_time_cv: float  # 变异系数（波动程度）
    error_rate_trend: float  # 错误率变化趋势（正值=恶化）
    consecutive_failures: int  # 连续失败次数
    last_ban_duration_s: Optional[float]  # 上次封禁时长
    total_requests_24h: int
    health_score: float = 0.0  # 综合健康分 [0, 1]

    @property
    def is_healthy(self) -> bool:
        return self.health_score >= 0.7


# ─────────────────────────────────────────────────────────────────────────────
# 趋势分析器
# ─────────────────────────────────────────────────────────────────────────────


class TrendAnalyzer:
    """
    基于滑动窗口的时序趋势分析器

    检测指标:
    - 成功率（success_rate）：持续下降 → 预警
    - 响应时间（response_time）：持续上升 → 预警
    - 错误率（error_rate）：连续上升 → 预警
    - 封禁频率（ban_frequency）：近期频繁封禁 → 高风险
    """

    WINDOW_SIZES = {
        "short": 20,   # 短窗口（最近 N 次请求）
        "medium": 100,  # 中窗口
        "long": 500,    # 长窗口（用于趋势计算）
    }

    def __init__(self):
        # 原始时序数据（按 source 存储）
        self._response_times: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self.WINDOW_SIZES["long"])
        )
        self._success_records: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self.WINDOW_SIZES["long"])
        )
        self._timestamps: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self.WINDOW_SIZES["long"])
        )
        self._ban_events: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=50)
        )  # 记录封禁事件时间

    def record(self, source: str, response_time_ms: float, success: bool):
        """记录一次请求结果"""
        now = datetime.now(timezone.utc)
        self._response_times[source].append(response_time_ms)
        self._success_records[source].append(1.0 if success else 0.0)
        self._timestamps[source].append(now)

    def record_ban(self, source: str, duration_seconds: float):
        """记录一次封禁事件"""
        self._ban_events[source].append({
            "timestamp": datetime.now(timezone.utc),
            "duration_s": duration_seconds,
        })

    def analyze(self, source: str) -> SourceHealth:
        """综合分析站点健康状态"""
        rt_series = list(self._response_times[source])
        sr_series = list(self._success_records[source])
        ts_series = list(self._timestamps[source])
        bans = list(self._ban_events[source])

        now = datetime.now(timezone.utc)

        # ── 短窗口指标（近20次）───────────────────────────────────────────────
        short_rt = rt_series[-self.WINDOW_SIZES["short"]:]
        short_sr = sr_series[-self.WINDOW_SIZES["short"]:]

        success_rate_1h = float(np.mean(short_sr)) if short_sr else 0.85

        # ── 长窗口指标（近500次）──────────────────────────────────────────────
        success_rate_7d = float(np.mean(sr_series)) if sr_series else 0.85

        avg_rt = float(np.mean(rt_series)) if rt_series else 2000.0
        std_rt = float(np.std(rt_series)) if len(rt_series) > 1 else 0.0
        cv = std_rt / avg_rt if avg_rt > 0 else 0.0

        # ── 错误率趋势（对比短窗口 vs 长窗口）────────────────────────────────
        if len(sr_series) >= self.WINDOW_SIZES["short"]:
            long_term = np.mean(sr_series)
            short_term = np.mean(sr_series[-self.WINDOW_SIZES["short"]:])
            # 正值 = 短期成功率低于长期平均 → 恶化
            error_rate_trend = (1 - short_term) - (1 - long_term)
        else:
            error_rate_trend = 0.0

        # ── 连续失败计数 ─────────────────────────────────────────────────────
        consecutive_failures = 0
        for s in reversed(sr_series):
            if s == 0.0:
                consecutive_failures += 1
            else:
                break

        # ── 近期封禁信息 ─────────────────────────────────────────────────────
        recent_bans = [
            b for b in bans
            if (now - b["timestamp"]).total_seconds() < 86400  # 24h内
        ]
        last_ban_duration = None
        if bans:
            last_ban_duration = bans[-1]["duration_s"]

        # ── 封禁频率（24h内封禁次数）─────────────────────────────────────────
        ban_frequency_24h = len(recent_bans)

        # ── 综合健康分计算 ───────────────────────────────────────────────────
        health = self._compute_health_score(
            success_rate_7d=success_rate_7d,
            success_rate_1h=success_rate_1h,
            cv=cv,
            error_rate_trend=error_rate_trend,
            consecutive_failures=consecutive_failures,
            ban_frequency_24h=ban_frequency_24h,
        )

        return SourceHealth(
            source=source,
            success_rate_7d=success_rate_7d,
            success_rate_1h=success_rate_1h,
            avg_response_time_ms=avg_rt,
            response_time_cv=cv,
            error_rate_trend=error_rate_trend,
            consecutive_failures=consecutive_failures,
            last_ban_duration_s=last_ban_duration,
            total_requests_24h=len(sr_series),
            health_score=health,
        )

    def _compute_health_score(
        self,
        success_rate_7d: float,
        success_rate_1h: float,
        cv: float,
        error_rate_trend: float,
        consecutive_failures: int,
        ban_frequency_24h: int,
    ) -> float:
        """
        综合健康分 [0, 1]
        越高越健康
        """
        # 基础分：成功率（权重 50%），起点 0.5 避免天花板 ~0.55
        base_score = 0.5 + success_rate_7d * 0.5

        # 短期波动惩罚（权重 15%）：CV 越高越不健康
        cv_penalty = max(0.0, min(0.15, cv * 0.15))
        score = base_score + (0.15 - cv_penalty)

        # 趋势惩罚（权重 20%）：错误率上升 → 扣分
        trend_penalty = max(0.0, min(0.20, error_rate_trend * 0.5))
        score -= trend_penalty

        # 连续失败惩罚（权重 15%）：每连续失败3次扣一层
        failure_penalty = min(0.15, consecutive_failures * 0.03)
        score -= failure_penalty

        # 封禁频率惩罚（权重 10%）：24h内封禁越多扣越狠
        ban_penalty = min(0.10, ban_frequency_24h * 0.025)
        score -= ban_penalty

        return max(0.0, min(1.0, score))

    def get_trend(self, source: str, metric: str = "success_rate") -> float:
        """
        获取趋势方向

        Returns:
            > 0: 上升趋势
            < 0: 下降趋势
            ≈ 0: 平稳
        """
        series = {
            "success_rate": self._success_records,
            "response_time": self._response_times,
        }.get(metric)

        if series is None or source not in series or len(series[source]) < 10:
            return 0.0

        data = list(series[source])
        mid = len(data) // 2
        first_half = data[:mid]
        second_half = data[mid:]

        if not first_half or not second_half:
            return 0.0

        first_mean = float(np.mean(first_half))
        second_mean = float(np.mean(second_half))

        if first_mean == 0:
            return 0.0

        # 相对变化率
        return (second_mean - first_half[0]) / (first_half[0] + 1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# 异常预测器
# ─────────────────────────────────────────────────────────────────────────────


class AnomalyPredictor:
    """
    站点异常预测引擎

    预测目标:
    1. Ban 概率：IP 被封禁的可能性
    2. Degradation 概率：服务质量显著下降的可能性

    算法:
    - 统计检测：滑动窗口 + 3σ 原则
    - 趋势外推：短期趋势线性回归
    - 规则引擎：基于专家知识的触发条件
    """

    # Ban 触发阈值
    BAN_CONSECUTIVE_FAILURES = 5
    BAN_SHORT_TERM_SUCCESS_RATE = 0.5  # 短窗口成功率低于此值 → Ban 预警
    BAN_SHORT_TERM_ERROR_RATE_THRESHOLD = 0.6

    # Degradation 触发阈值
    DEGRADATION_TREND_THRESHOLD = -0.05  # 成功率趋势低于此值
    DEGRADATION_RT_INCREASE_THRESHOLD = 1.5  # 响应时间上升超过 1.5x

    def __init__(self, trend_analyzer: TrendAnalyzer):
        self.trend_analyzer = trend_analyzer
        self._predictions: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=100)
        )  # 预测历史

    def predict(self, source: str) -> RiskScore:
        """预测站点的风险等级"""
        health = self.trend_analyzer.analyze(source)

        # ── Ban 概率计算 ───────────────────────────────────────────────────
        ban_prob = self._compute_ban_probability(health)

        # ── Degradation 概率计算 ───────────────────────────────────────────
        degradation_prob = self._compute_degradation_probability(health, source)

        # ── 综合风险评分 ───────────────────────────────────────────────────
        risk_score = max(ban_prob, degradation_prob)
        risk_level = self._score_to_level(risk_score)

        # ── 推荐动作 ───────────────────────────────────────────────────────
        recommendation = self._get_recommendation(risk_level, health)

        # ── 置信度（基于数据量）─────────────────────────────────────────────
        confidence = min(1.0, health.total_requests_24h / 100.0)

        score = RiskScore(
            source=source,
            risk_level=risk_level,
            score=risk_score,
            ban_probability=ban_prob,
            degradation_probability=degradation_prob,
            confidence=confidence,
            factors={
                "success_rate_7d": round(health.success_rate_7d, 4),
                "success_rate_1h": round(health.success_rate_1h, 4),
                "response_time_cv": round(health.response_time_cv, 4),
                "error_rate_trend": round(health.error_rate_trend, 4),
                "consecutive_failures": health.consecutive_failures,
                "ban_frequency_24h": len(list(self.trend_analyzer._ban_events[source])),
            },
            recommendation=recommendation,
        )

        self._predictions[source].append(score)
        return score

    def _compute_ban_probability(self, health: SourceHealth) -> float:
        """计算 Ban 概率 [0, 1]"""
        prob = 0.0

        # 因子1：连续失败次数（最强信号）
        if health.consecutive_failures >= self.BAN_CONSECUTIVE_FAILURES:
            prob = max(prob, 0.9)
        elif health.consecutive_failures >= 3:
            prob = max(prob, 0.6)
        elif health.consecutive_failures >= 2:
            prob = max(prob, 0.3)

        # 因子2：短窗口成功率
        if health.success_rate_1h < self.BAN_SHORT_TERM_SUCCESS_RATE:
            shortfall = self.BAN_SHORT_TERM_SUCCESS_RATE - health.success_rate_1h
            prob = max(prob, min(0.8, shortfall * 2))

        # 因子3：错误率上升趋势
        if health.error_rate_trend > 0.3:
            prob = max(prob, 0.7)
        elif health.error_rate_trend > 0.15:
            prob = max(prob, 0.4)

        # 因子4：响应时间波动
        if health.response_time_cv > 1.0:  # 高波动
            prob = max(prob, 0.5)
        elif health.response_time_cv > 0.5:
            prob = max(prob, 0.25)

        # 因子5：近期封禁历史
        if health.last_ban_duration_s is not None:
            if health.last_ban_duration_s > 300:  # 之前被封 > 5min
                prob = max(prob, 0.3)

        return min(1.0, prob)

    def _compute_degradation_probability(
        self, health: SourceHealth, source: str
    ) -> float:
        """计算服务质量下降概率 [0, 1]"""
        prob = 0.0

        # 因子1：成功率下降趋势
        if health.error_rate_trend > 0.2:
            prob = max(prob, 0.7)
        elif health.error_rate_trend > 0.1:
            prob = max(prob, 0.4)

        # 因子2：响应时间趋势
        rt_trend = self.trend_analyzer.get_trend(source, "response_time")
        if rt_trend > 0.5:  # 响应时间上升 > 50%
            prob = max(prob, 0.6)

        # 因子3：CV 波动
        if health.response_time_cv > 0.8:
            prob = max(prob, 0.5)

        # 因子4：成功率短期 vs 长期差异
        rate_diff = health.success_rate_7d - health.success_rate_1h
        if rate_diff > 0.2:  # 短期成功率显著低于长期
            prob = max(prob, 0.6)

        return min(1.0, prob)

    def _score_to_level(self, score: float) -> RiskLevel:
        if score >= 0.8:
            return RiskLevel.CRITICAL
        elif score >= 0.6:
            return RiskLevel.HIGH
        elif score >= 0.3:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _get_recommendation(self, risk_level: RiskLevel, health: SourceHealth) -> str:
        if risk_level == RiskLevel.CRITICAL:
            return "立即暂停采集，进入恢复冷却期（15-30min）"
        elif risk_level == RiskLevel.HIGH:
            return "大幅降低采集频率，切换备用站点或代理"
        elif risk_level == RiskLevel.MEDIUM:
            return "适度降低采集密度，密切监控指标变化"
        elif risk_level == RiskLevel.LOW:
            if health.is_healthy:
                return "正常运行，保持当前采集节奏"
            else:
                return "站点尚未完全恢复，保持观察"
        return "正常运行"

    def get_prediction_history(self, source: str) -> list:
        """获取预测历史"""
        return list(self._predictions[source])


# ─────────────────────────────────────────────────────────────────────────────
# 预防性调度器
# ─────────────────────────────────────────────────────────────────────────────


class PreventiveScheduler:
    """
    预防性调度器

    在 DynamicPriorityEngine + AdaptiveIntervalManager 的基础上，
    集成 AnomalyPredictor，实现"预测驱动"的调度决策：

    1. 预测风险 → 动态调整优先级
    2. 预测风险 → 提前延长采集间隔
    3. 预测风险 → 触发站点健康检查
    4. 预测风险 → 切换备用数据源
    """

    # 风险等级对应的间隔倍数
    INTERVAL_MULTIPLIERS = {
        RiskLevel.LOW: 1.0,
        RiskLevel.MEDIUM: 1.5,
        RiskLevel.HIGH: 3.0,
        RiskLevel.CRITICAL: 10.0,
    }

    # 风险等级对应的优先级折扣
    PRIORITY_DISCOUNTS = {
        RiskLevel.LOW: 1.0,
        RiskLevel.MEDIUM: 0.8,
        RiskLevel.HIGH: 0.5,
        RiskLevel.CRITICAL: 0.1,
    }

    def __init__(
        self,
        base_scheduler: "SmartScheduler",
        trend_analyzer: TrendAnalyzer,
    ):
        self.base_scheduler = base_scheduler
        self.trend_analyzer = trend_analyzer
        self.predictor = AnomalyPredictor(trend_analyzer)

        # 每个站点的风险缓存（避免重复计算）
        self._risk_cache: dict[str, RiskScore] = {}
        self._risk_cache_time: dict[str, datetime] = {}
        self._risk_cache_ttl_s = 30  # 缓存 30 秒

    async def get_risk_score(self, source: str) -> RiskScore:
        """获取站点风险评分（带缓存）"""
        now = datetime.now(timezone.utc)
        cached_time = self._risk_cache_time.get(source)

        if (
            source in self._risk_cache
            and cached_time is not None
            and (now - cached_time).total_seconds() < self._risk_cache_ttl_s
        ):
            return self._risk_cache[source]

        score = self.predictor.predict(source)
        self._risk_cache[source] = score
        self._risk_cache_time[source] = now
        return score

    async def get_adjusted_interval(
        self, source: str, base_interval: float
    ) -> float:
        """获取风险调整后的采集间隔"""
        risk = await self.get_risk_score(source)
        multiplier = self.INTERVAL_MULTIPLIERS[risk.risk_level]
        adjusted = base_interval * multiplier

        if risk.risk_level == RiskLevel.CRITICAL:
            # CRITICAL: 强制使用最小间隔而非乘数上限
            adjusted = max(60.0, min(adjusted, 600.0))
        elif risk.risk_level == RiskLevel.HIGH:
            adjusted = max(30.0, min(adjusted, 300.0))

        logger.debug(
            f"[PreventiveScheduler] {source} risk={risk.risk_level.value} "
            f"base={base_interval:.2f}s → adjusted={adjusted:.2f}s"
        )
        return adjusted

    async def get_adjusted_priority(
        self, source: str, base_priority: float
    ) -> float:
        """获取风险调整后的优先级"""
        risk = await self.get_risk_score(source)
        discount = self.PRIORITY_DISCOUNTS[risk.risk_level]
        return base_priority * discount

    async def should_defer_task(
        self, source: str, task_priority: float
    ) -> tuple[bool, str]:
        """
        判断任务是否应推迟

        Returns:
            (should_defer, reason)
        """
        risk = await self.get_risk_score(source)

        if risk.risk_level == RiskLevel.CRITICAL:
            return True, f"CRITICAL 风险站点（{risk.score:.2f}），推迟 15min"

        if risk.risk_level == RiskLevel.HIGH:
            # 高优先级任务不推迟，低优先级才推迟
            if task_priority < 0.5:
                return True, "HIGH 风险站点，低优先级任务推迟"

        if risk.ban_probability > 0.7:
            return True, f"Ban 概率 {risk.ban_probability:.2f}，预防性推迟"

        return False, ""

    async def record_request(
        self, source: str, response_time_ms: float, success: bool
    ):
        """记录请求结果（同步到趋势分析器）"""
        self.trend_analyzer.record(source, response_time_ms, success)
        # 清除缓存，强制重新预测
        self._risk_cache.pop(source, None)
        self._risk_cache_time.pop(source, None)

    def record_ban(self, source: str, duration_seconds: float):
        """记录封禁事件"""
        self.trend_analyzer.record_ban(source, duration_seconds)
        self._risk_cache.pop(source, None)
        self._risk_cache_time.pop(source, None)

    async def get_all_risks(self) -> dict[str, RiskScore]:
        """获取所有站点的当前风险评分"""
        sources = set(self.trend_analyzer._success_records.keys())
        return {s: await self.get_risk_score(s) for s in sources}

    async def get_health_report(self) -> dict:
        """生成站点健康报告"""
        risks = await self.get_all_risks()
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sources": {
                source: {
                    "risk_level": r.risk_level.value,
                    "score": round(r.score, 4),
                    "ban_probability": round(r.ban_probability, 4),
                    "degradation_probability": round(r.degradation_probability, 4),
                    "confidence": round(r.confidence, 4),
                    "recommendation": r.recommendation,
                    "factors": r.factors,
                }
                for source, r in risks.items()
            },
        }


# ─────────────────────────────────────────────────────────────────────────────
# 适配器：集成到 SmartScheduler
# ─────────────────────────────────────────────────────────────────────────────


class SmartSchedulerWithPrediction:
    """
    集成预测能力的智能调度器（SmartScheduler 增强版）

    包装 SmartScheduler，在任务调度前查询风险评分，
    自动调整间隔和优先级。
    """

    def __init__(self, base_scheduler: "SmartScheduler"):
        self.base_scheduler = base_scheduler
        self.trend_analyzer = TrendAnalyzer()
        self.preventive_scheduler = PreventiveScheduler(
            base_scheduler=base_scheduler,
            trend_analyzer=self.trend_analyzer,
        )

        # 转发：确保记录数据到趋势分析器
        self._original_record_success = base_scheduler.priority_engine.record_success
        self._original_record_failure = base_scheduler.priority_engine.record_failure

        base_scheduler.priority_engine.record_success = self._patched_record_success
        base_scheduler.priority_engine.record_failure = self._patched_record_failure

    def _patched_record_success(self, source: str, response_time_ms: float):
        self._original_record_success(source, response_time_ms)
        asyncio.create_task(
            self.preventive_scheduler.record_request(source, response_time_ms, True)
        )

    def _patched_record_failure(self, source: str, response_time_ms: float = None):
        self._original_record_failure(source, response_time_ms)
        asyncio.create_task(
            self.preventive_scheduler.record_request(
                source, response_time_ms or 0, False
            )
        )

    async def get_interval(self, task: "CrawlTask") -> float:
        """获取预防性调整后的采集间隔"""
        base_interval = await self.base_scheduler.interval_manager.get_interval(task)
        return await self.preventive_scheduler.get_adjusted_interval(
            task.source, base_interval
        )

    async def should_skip(self, task: "CrawlTask") -> tuple[bool, str]:
        """
        判断是否应跳过任务（预防性调度）

        Returns:
            (should_skip, reason)
        """
        # 先检查间隔保护
        base_skip = await self.base_scheduler.interval_manager.should_skip(task)
        if base_skip:
            return True, "间隔保护"

        # 再检查风险预测
        return await self.preventive_scheduler.should_defer_task(
            task.source, task.priority_dynamic
        )

    def record_ban(self, source: str, duration_seconds: int):
        """记录封禁事件"""
        self.preventive_scheduler.record_ban(source, duration_seconds)
        self.base_scheduler.interval_manager.apply_ban(source, duration_seconds)

    @property
    def interval_manager(self):
        return self.base_scheduler.interval_manager

    @property
    def priority_engine(self):
        return self.base_scheduler.priority_engine

    async def get_health_report(self) -> dict:
        return await self.preventive_scheduler.get_health_report()


# ─────────────────────────────────────────────────────────────────────────────
# 示例 / 测试
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    async def demo():
        from smart_scheduler import SmartScheduler

        # 初始化
        base = SmartScheduler(max_concurrent=3)
        enhanced = SmartSchedulerWithPrediction(base)
        ps = enhanced.preventive_scheduler

        print("\n=== 模拟正常站点 ===")
        for i in range(20):
            ps.record_request("healthy_site", 500 + i * 5, True)

        risk = await ps.get_risk_score("healthy_site")
        print(f"  风险: {risk.risk_level.value} | 评分: {risk.score:.4f}")
        print(f"  推荐: {risk.recommendation}")

        print("\n=== 模拟逐渐恶化的站点 ===")
        for i in range(30):
            success = i < 25  # 前25次成功，后5次失败（模拟触发Ban）
            ps.record_request("degrading_site", 500 + i * 50, success)

        risk = await ps.get_risk_score("degrading_site")
        print(f"  风险: {risk.risk_level.value} | 评分: {risk.score:.4f}")
        print(f"  Ban概率: {risk.ban_probability:.4f}")
        print(f"  降级概率: {risk.degradation_probability:.4f}")
        print(f"  推荐: {risk.recommendation}")
        print(f"  因子: {risk.factors}")

        print("\n=== 模拟已触发Ban的站点 ===")
        ps.record_ban("banned_site", 300)
        for i in range(10):
            ps.record_request("banned_site", 5000, False)
        ps.record_ban("banned_site", 600)

        risk = await ps.get_risk_score("banned_site")
        print(f"  风险: {risk.risk_level.value} | 评分: {risk.score:.4f}")
        print(f"  Ban概率: {risk.ban_probability:.4f}")
        print(f"  推荐: {risk.recommendation}")

        print("\n=== 调整后采集间隔 ===")
        base_interval = 2.0
        for source in ["healthy_site", "degrading_site", "banned_site"]:
            risk = await ps.get_risk_score(source)
            adjusted = await ps.get_adjusted_interval(source, base_interval)
            print(f"  {source}: base={base_interval:.1f}s → adjusted={adjusted:.1f}s")

        print("\n=== 健康报告 ===")
        report = await enhanced.get_health_report()
        for source, info in report["sources"].items():
            print(f"  {source}: {info['risk_level']} | score={info['score']}")

    asyncio.run(demo())
