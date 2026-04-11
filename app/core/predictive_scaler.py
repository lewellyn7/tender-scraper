"""
预测性扩容引擎 - 根据历史数据预测负载并自动调整资源配置

功能：
1. TrendAnalyzer: 分析历史采集数据，预测未来负载
2. ScalingPolicy: 定义扩容/缩容策略规则
3. ResourcePredictor: 预测未来N小时的资源需求
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


# ── Historical Data Point ────────────────────────────────────


@dataclass
class LoadSnapshot:
    """负载快照"""
    timestamp: datetime
    tenders_found: int = 0
    tenders_matched: int = 0
    duration_ms: int = 0
    success: bool = True
    error_message: str = ""
    concurrent_workers: int = 1
    memory_mb: float = 0.0
    cpu_percent: float = 0.0


# ── Trend Analysis ───────────────────────────────────────────


class TrendAnalyzer:
    """
    历史负载趋势分析器

    分析最近N条采集记录，预测：
    1. 工作日 vs 周末 采集量差异
    2. 每日高峰时段
    3. 采集量趋势（上升/下降/平稳）
    4. 异常检测（突然增加/减少）
    """

    def __init__(self, history_maxlen: int = 200):
        self.history: deque[LoadSnapshot] = deque(maxlen=history_maxlen)

    def record(self, snapshot: LoadSnapshot):
        """记录一条采集快照"""
        self.history.append(snapshot)

    def record_run(
        self,
        tenders_found: int,
        tenders_matched: int,
        duration_ms: int,
        success: bool,
        error: str = "",
    ):
        """快捷记录（从采集器调用）"""
        self.record(LoadSnapshot(
            timestamp=datetime.now(),
            tenders_found=tenders_found,
            tenders_matched=tenders_matched,
            duration_ms=duration_ms,
            success=success,
            error_message=error,
        ))

    def _is_workday(self, dt: datetime) -> bool:
        return dt.weekday() < 5  # Mon-Fri

    def analyze(self) -> Dict[str, Any]:
        """返回趋势分析报告"""
        if len(self.history) < 3:
            return {"status": "insufficient_data", "samples": len(self.history)}

        snapshots = list(self.history)

        # 1. 基础统计
        founds = [s.tenders_found for s in snapshots]
        matched = [s.tenders_matched for s in snapshots]
        durations = [s.duration_ms for s in snapshots if s.success]

        avg_found = sum(founds) / len(founds)
        avg_matched = sum(matched) / len(matched)
        avg_duration = sum(durations) / len(durations) if durations else 0
        success_rate = sum(1 for s in snapshots if s.success) / len(snapshots)

        # 2. 工作日 vs 周末
        workday_found = [s.tenders_found for s in snapshots if self._is_workday(s.timestamp)]
        weekend_found = [s.tenders_found for s in snapshots if not self._is_workday(s.timestamp)]
        workday_avg = sum(workday_found) / len(workday_found) if workday_found else 0
        weekend_avg = sum(weekend_found) / len(weekend_found) if weekend_found else 0

        # 3. 时段分析（小时粒度）
        hourly_avg: Dict[int, List[int]] = {}
        for s in snapshots:
            hour = s.timestamp.hour
            hourly_avg.setdefault(hour, []).append(s.tenders_found)

        peak_hours = sorted(
            [(h, sum(v) / len(v)) for h, v in hourly_avg.items()],
            key=lambda x: x[1],
            reverse=True,
        )[:3]

        # 4. 趋势判断（最近10条 vs 前10条）
        recent = snapshots[-10:]
        older = snapshots[-20:-10] if len(snapshots) >= 20 else snapshots[:10]
        if recent and older:
            recent_avg = sum(s.tenders_found for s in recent) / len(recent)
            older_avg = sum(s.tenders_found for s in older) / len(older)
            trend_ratio = recent_avg / older_avg if older_avg > 0 else 1.0
            if trend_ratio > 1.2:
                trend = "rising"
            elif trend_ratio < 0.8:
                trend = "falling"
            else:
                trend = "stable"
        else:
            trend = "unknown"
            trend_ratio = 1.0

        # 5. 异常检测
        if founds:
            std_dev = (sum((x - avg_found) ** 2 for x in founds) / len(founds)) ** 0.5
            last = snapshots[-1].tenders_found
            is_anomaly = abs(last - avg_found) > 2 * std_dev if std_dev > 0 else False
        else:
            is_anomaly = False

        return {
            "status": "ok",
            "samples": len(snapshots),
            "avg_tenders_found": round(avg_found, 1),
            "avg_tenders_matched": round(avg_matched, 1),
            "avg_duration_ms": round(avg_duration, 1),
            "success_rate": round(success_rate, 3),
            "workday_avg": round(workday_avg, 1),
            "weekend_avg": round(weekend_avg, 1),
            "peak_hours": [{"hour": h, "avg_found": round(avg, 1)} for h, avg in peak_hours],
            "trend": trend,
            "trend_ratio": round(trend_ratio, 2),
            "last_tenders_found": snapshots[-1].tenders_found,
            "is_anomaly": is_anomaly,
        }


# ── Scaling Policy ───────────────────────────────────────────


@dataclass
class ScalingAction:
    """扩容/缩容动作"""
    action: str  # "scale_up" | "scale_down" | "maintain"
    reason: str
    recommended_workers: int
    confidence: float  # 0-1
    timestamp: datetime = field(default_factory=datetime.now)


class ScalingPolicy:
    """
    扩容策略引擎

    规则：
    1. 采集量 > 阈值 → 扩容
    2. 连续成功 + 上升趋势 → 加快扩容
    3. 失败率升高 → 缩容保护
    4. 周末/夜间 → 降低资源
    """

    def __init__(
        self,
        scale_up_threshold: int = 50,       # 平均采集量 > 此值则扩容
        scale_down_threshold: int = 10,      # 平均采集量 < 此值则缩容
        min_workers: int = 1,
        max_workers: int = 8,
    ):
        self.scale_up_threshold = scale_up_threshold
        self.scale_down_threshold = scale_down_threshold
        self.min_workers = min_workers
        self.max_workers = max_workers

    def evaluate(
        self,
        analysis: Dict[str, Any],
        current_workers: int,
    ) -> ScalingAction:
        """基于分析结果返回扩容决策"""
        if analysis.get("status") != "ok":
            return ScalingAction(
                action="maintain",
                reason="数据不足",
                recommended_workers=current_workers,
                confidence=0.0,
            )

        avg_found = analysis.get("avg_tenders_found", 0)
        success_rate = analysis.get("success_rate", 1.0)
        trend = analysis.get("trend", "stable")
        is_anomaly = analysis.get("is_anomaly", False)
        now = datetime.now()
        is_workday = now.weekday() < 5
        hour = now.hour

        # 工作时间（9-18点）加权
        business_hours = 9 <= hour <= 18

        # 异常检测 → 保持稳定
        if is_anomaly:
            return ScalingAction(
                action="maintain",
                reason=f"检测到异常值（{analysis.get('last_tenders_found')}），保持稳定",
                recommended_workers=current_workers,
                confidence=0.8,
            )

        # 成功率过低 → 缩容保护
        if success_rate < 0.5:
            new_workers = max(self.min_workers, current_workers - 1)
            return ScalingAction(
                action="scale_down",
                reason=f"成功率过低（{success_rate:.0%}），缩容保护",
                recommended_workers=new_workers,
                confidence=0.9,
            )

        # 上升趋势 + 高采集量 → 扩容
        if trend == "rising" and avg_found > self.scale_up_threshold:
            new_workers = min(self.max_workers, current_workers + 1)
            return ScalingAction(
                action="scale_up",
                reason=f"上升趋势（{analysis.get('trend_ratio')}x）+ 高采集量（{avg_found:.0f}条），扩容",
                recommended_workers=new_workers,
                confidence=0.85,
            )

        # 持续高采集量 + 工作时间 → 扩容
        if business_hours and avg_found > self.scale_up_threshold:
            new_workers = min(self.max_workers, current_workers + 1)
            return ScalingAction(
                action="scale_up",
                reason=f"工作时间高负荷（{avg_found:.0f}条），扩容",
                recommended_workers=new_workers,
                confidence=0.7,
            )

        # 下降趋势 + 低采集量 + 非工作时间 → 缩容
        if trend == "falling" and avg_found < self.scale_down_threshold and not business_hours:
            new_workers = max(self.min_workers, current_workers - 1)
            return ScalingAction(
                action="scale_down",
                reason=f"下降趋势 + 非高峰期 + 低采集量，缩容",
                recommended_workers=new_workers,
                confidence=0.75,
            )

        # 夜间/周末 → 自动降低
        if not business_hours and not is_workday:
            if current_workers > self.min_workers:
                new_workers = max(self.min_workers, current_workers - 1)
                return ScalingAction(
                    action="scale_down",
                    reason="非工作时间，降低资源",
                    recommended_workers=new_workers,
                    confidence=0.6,
                )

        return ScalingAction(
            action="maintain",
            reason="各项指标正常，保持当前资源配置",
            recommended_workers=current_workers,
            confidence=0.9,
        )


# ── Resource Predictor ──────────────────────────────────────


class ResourcePredictor:
    """
    资源需求预测器

    基于历史数据预测未来N小时的：
    1. 预期采集量
    2. 建议 worker 数量
    3. 预估存储使用
    """

    def __init__(self, trend_analyzer: TrendAnalyzer):
        self.analyzer = trend_analyzer

    def predict_next_hours(self, hours: int = 4) -> Dict[str, Any]:
        """预测接下来 N 小时的资源需求"""
        analysis = self.analyzer.analyze()
        if analysis.get("status") != "ok":
            return {"status": "insufficient_data"}

        now = datetime.now()
        predictions = []

        for i in range(hours):
            target_time = now + timedelta(hours=i)
            hour = target_time.hour
            is_workday = target_time.weekday() < 5

            # 估算该时段平均采集量
            peak_info = {p["hour"]: p["avg_found"] for p in analysis.get("peak_hours", [])}
            hour_avg = peak_info.get(hour, analysis["avg_tenders_found"])

            # 周末折扣
            if not is_workday:
                hour_avg *= 0.6

            # 夜间折扣
            if not (9 <= hour <= 18):
                hour_avg *= 0.3

            predictions.append({
                "time": target_time.strftime("%H:00"),
                "estimated_tenders": round(hour_avg, 0),
                "is_workday": is_workday,
                "is_business_hours": 9 <= hour <= 18,
            })

        # 推荐 workers
        avg_found = analysis["avg_tenders_found"]
        if avg_found > 100:
            recommended_workers = 4
        elif avg_found > 50:
            recommended_workers = 3
        elif avg_found > 20:
            recommended_workers = 2
        else:
            recommended_workers = 1

        return {
            "status": "ok",
            "predictions": predictions,
            "recommended_workers": recommended_workers,
            "trend": analysis.get("trend", "unknown"),
            "confidence": 0.6 if analysis.get("trend") == "stable" else 0.75,
        }
