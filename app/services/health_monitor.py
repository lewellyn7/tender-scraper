"""HealthMonitorService — 采集系统健康度监控服务

指标收集、阈值告警、历史趋势
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from loguru import logger

# ── 健康度指标定义 ──────────────────────────────────────
HEALTH_METRICS = {
    "crawl_success_rate": {
        "label": "采集成功率",
        "target": 0.95,
        "unit": "%",
        "direction": "higher",   # 越高越好
        "threshold_low": 0.80,
    },
    "crawl_avg_latency_ms": {
        "label": "平均采集延迟",
        "target": 2000,
        "unit": "ms",
        "direction": "lower",    # 越低越好
        "threshold_high": 5000,
    },
    "crawl_items_per_hour": {
        "label": "采集吞吐量",
        "target": 100,
        "unit": "项/时",
        "direction": "higher",
        "threshold_low": 10,
    },
    "self_heal_rate": {
        "label": "自愈率",
        "target": 0.80,
        "unit": "%",
        "direction": "higher",
        "threshold_low": 0.50,
    },
    "ban_escape_rate": {
        "label": "封禁逃脱率",
        "target": 0.90,
        "unit": "%",
        "direction": "higher",
        "threshold_low": 0.60,
    },
}


@dataclass
class HealthSnapshot:
    """单次健康度快照"""
    timestamp: str
    crawl_success_rate: float      # 0-1
    crawl_avg_latency_ms: float
    crawl_items_per_hour: float
    self_heal_rate: float          # 0-1
    ban_escape_rate: float         # 0-1
    alerts: List[str] = field(default_factory=list)
    overall_score: float = 0.0     # 0-100


class HealthMonitorService:
    """
    采集系统健康度监控

    收集运行时指标，支持阈值告警，提供健康度评分。
    数据存储在内存中（重启后重置），生产环境建议接入 Redis/DB。
    """

    def __init__(self):
        # 滑动窗口计数器（内存）
        self._crawl_total = 0
        self._crawl_success = 0
        self._crawl_latencies: List[float] = []   # ms
        self._crawl_timestamps: List[float] = []  # unix ts
        self._heal_success = 0
        self._heal_total = 0
        self._ban_escape = 0
        self._ban_total = 0

        # 告警状态（防止重复告警）
        self._alerted: Dict[str, bool] = {}

        # 历史快照（最近 30 天）
        self._snapshots: List[HealthSnapshot] = []

        # 窗口大小（秒）
        self._window_seconds = 3600  # 1-hour sliding window for throughput

    # ── 指标更新 ──────────────────────────────────────────

    def record_crawl(self, success: bool, latency_ms: float):
        """记录单次采集结果"""
        now = time.time()
        self._crawl_total += 1
        if success:
            self._crawl_success += 1
        self._crawl_latencies.append(latency_ms)
        self._crawl_timestamps.append(now)
        self._prune_old_entries(now)

    def record_self_heal(self, success: bool):
        """记录自愈结果"""
        self._heal_total += 1
        if success:
            self._heal_success += 1

    def record_ban_escape(self, escaped: bool):
        """记录封禁逃脱"""
        self._ban_total += 1
        if escaped:
            self._ban_escape += 1

    def _prune_old_entries(self, now: float):
        """清理滑动窗口外的旧数据"""
        cutoff = now - self._window_seconds
        self._crawl_timestamps = [t for t in self._crawl_timestamps if t > cutoff]
        # 保留最近 N 条延迟数据
        if len(self._crawl_latencies) > 1000:
            self._crawl_latencies = self._crawl_latencies[-1000:]

    # ── 指标计算 ──────────────────────────────────────────

    def _calc_success_rate(self) -> float:
        if self._crawl_total == 0:
            return 1.0
        return self._crawl_success / self._crawl_total

    def _calc_avg_latency(self) -> float:
        if not self._crawl_latencies:
            return 0.0
        return sum(self._crawl_latencies) / len(self._crawl_latencies)

    def _calc_throughput(self) -> float:
        """过去 1 小时的采集项数 / 1 小时 = 项/时"""
        self._prune_old_entries(time.time())
        return len(self._crawl_timestamps)

    def _calc_self_heal_rate(self) -> float:
        if self._heal_total == 0:
            return 1.0
        return self._heal_success / self._heal_total

    def _calc_ban_escape_rate(self) -> float:
        if self._ban_total == 0:
            return 1.0
        return self._ban_escape / self._ban_total

    def _score_metric(self, key: str, value: float) -> float:
        """将指标值归一化到 0-100 分"""
        meta = HEALTH_METRICS.get(key)
        if not meta:
            return 50.0

        if meta["direction"] == "higher":
            # 目标值 = 100 分，threshold = 0 分
            target = meta["target"]
            threshold_key = "threshold_low"
            threshold = meta.get(threshold_key, target * 0.5)
            if value >= target:
                return 100.0
            if value <= threshold:
                return 0.0
            return (value - threshold) / (target - threshold) * 100.0
        else:
            # direction == "lower": 目标值 = 100 分，threshold = 0 分
            target = meta["target"]
            threshold = meta.get("threshold_high", target * 2)
            if value <= target:
                return 100.0
            if value >= threshold:
                return 0.0
            return (threshold - value) / (threshold - target) * 100.0

    def _check_alerts(self, snapshot: HealthSnapshot):
        """检查是否触发阈值告警"""
        alerts = []
        checks = [
            ("crawl_success_rate", snapshot.crawl_success_rate, "lower"),
            ("crawl_avg_latency_ms", snapshot.crawl_avg_latency_ms, "higher"),
            ("self_heal_rate", snapshot.self_heal_rate, "lower"),
            ("ban_escape_rate", snapshot.ban_escape_rate, "lower"),
        ]
        for key, value, direction in checks:
            meta = HEALTH_METRICS.get(key, {})
            threshold = meta.get("threshold_low" if direction == "lower" else "threshold_high")
            if threshold is None:
                continue
            alert_key = f"{key}_alerted"
            triggered = (direction == "lower" and value < threshold) or \
                        (direction == "higher" and value > threshold)
            if triggered and not self._alerted.get(alert_key):
                alerts.append(f"⚠️ {meta['label']} {value:.1% if 'rate' in key or key in ('self_heal_rate', 'ban_escape_rate') else ''} 低于阈值 {threshold:.1% if 'rate' in key or key in ('self_heal_rate', 'ban_escape_rate') else threshold}")
                self._alerted[alert_key] = True
            elif not triggered:
                self._alerted[alert_key] = False
        return alerts

    # ── 快照生成 ──────────────────────────────────────────

    def take_snapshot(self) -> HealthSnapshot:
        """生成当前健康度快照"""
        success_rate = self._calc_success_rate()
        latency = self._calc_avg_latency()
        throughput = self._calc_throughput()
        self_heal = self._calc_self_heal_rate()
        ban_escape = self._calc_ban_escape_rate()

        snapshot = HealthSnapshot(
            timestamp=datetime.now().isoformat(),
            crawl_success_rate=success_rate,
            crawl_avg_latency_ms=latency,
            crawl_items_per_hour=throughput,
            self_heal_rate=self_heal,
            ban_escape_rate=ban_escape,
        )

        # 计算总分
        scores = [
            self._score_metric("crawl_success_rate", success_rate),
            self._score_metric("crawl_avg_latency_ms", latency),
            self._score_metric("crawl_items_per_hour", throughput),
            self._score_metric("self_heal_rate", self_heal),
            self._score_metric("ban_escape_rate", ban_escape),
        ]
        snapshot.overall_score = round(sum(scores) / len(scores), 1)

        # 告警检查
        snapshot.alerts = self._check_alerts(snapshot)

        # 保存历史（保留 30 天）
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 30 * 24:  # 假设每小时一次，最多 30 天
            self._snapshots = self._snapshots[-30 * 24:]

        return snapshot

    # ── 历史趋势 ──────────────────────────────────────────

    def get_trends(self, days: int = 7) -> List[Dict]:
        """获取最近 N 天的趋势数据（按天聚合）"""
        cutoff = datetime.now() - timedelta(days=days)
        recent = [s for s in self._snapshots if datetime.fromisoformat(s.timestamp) > cutoff]

        # 按天聚合
        by_day: Dict[str, Dict] = defaultdict(lambda: {
            "success_rates": [], "latencies": [], "throughputs": [],
            "heal_rates": [], "ban_rates": [], "scores": [], "count": 0,
        })
        for s in recent:
            day = s.timestamp[:10]
            d = by_day[day]
            d["success_rates"].append(s.crawl_success_rate)
            d["latencies"].append(s.crawl_avg_latency_ms)
            d["throughputs"].append(s.crawl_items_per_hour)
            d["heal_rates"].append(s.self_heal_rate)
            d["ban_rates"].append(s.ban_escape_rate)
            d["scores"].append(s.overall_score)
            d["count"] += 1

        result = []
        for day, d in sorted(by_day.items()):
            result.append({
                "date": day,
                "crawl_success_rate": round(sum(d["success_rates"]) / len(d["success_rates"]), 4) if d["success_rates"] else 0,
                "crawl_avg_latency_ms": round(sum(d["latencies"]) / len(d["latencies"]), 1) if d["latencies"] else 0,
                "crawl_items_per_hour": round(sum(d["throughputs"]) / len(d["throughputs"]), 1) if d["throughputs"] else 0,
                "self_heal_rate": round(sum(d["heal_rates"]) / len(d["heal_rates"]), 4) if d["heal_rates"] else 0,
                "ban_escape_rate": round(sum(d["ban_rates"]) / len(d["ban_rates"]), 4) if d["ban_rates"] else 0,
                "overall_score": round(sum(d["scores"]) / len(d["scores"]), 1) if d["scores"] else 0,
            })
        return result

    # ── 公开 API ──────────────────────────────────────────

    def get_current_status(self) -> Dict:
        """获取当前健康度状态（供 /api/health/status 使用）"""
        snapshot = self.take_snapshot()
        return {
            "timestamp": snapshot.timestamp,
            "overall_score": snapshot.overall_score,
            "metrics": {
                "crawl_success_rate": {
                    "value": snapshot.crawl_success_rate,
                    "label": HEALTH_METRICS["crawl_success_rate"]["label"],
                    "target": HEALTH_METRICS["crawl_success_rate"]["target"],
                    "unit": "%",
                    "score": self._score_metric("crawl_success_rate", snapshot.crawl_success_rate),
                },
                "crawl_avg_latency_ms": {
                    "value": snapshot.crawl_avg_latency_ms,
                    "label": HEALTH_METRICS["crawl_avg_latency_ms"]["label"],
                    "target": HEALTH_METRICS["crawl_avg_latency_ms"]["target"],
                    "unit": "ms",
                    "score": self._score_metric("crawl_avg_latency_ms", snapshot.crawl_avg_latency_ms),
                },
                "crawl_items_per_hour": {
                    "value": snapshot.crawl_items_per_hour,
                    "label": HEALTH_METRICS["crawl_items_per_hour"]["label"],
                    "target": HEALTH_METRICS["crawl_items_per_hour"]["target"],
                    "unit": "项/时",
                    "score": self._score_metric("crawl_items_per_hour", snapshot.crawl_items_per_hour),
                },
                "self_heal_rate": {
                    "value": snapshot.self_heal_rate,
                    "label": HEALTH_METRICS["self_heal_rate"]["label"],
                    "target": HEALTH_METRICS["self_heal_rate"]["target"],
                    "unit": "%",
                    "score": self._score_metric("self_heal_rate", snapshot.self_heal_rate),
                },
                "ban_escape_rate": {
                    "value": snapshot.ban_escape_rate,
                    "label": HEALTH_METRICS["ban_escape_rate"]["label"],
                    "target": HEALTH_METRICS["ban_escape_rate"]["target"],
                    "unit": "%",
                    "score": self._score_metric("ban_escape_rate", snapshot.ban_escape_rate),
                },
            },
            "alerts": snapshot.alerts,
            "trends_7d": self.get_trends(7),
            "trends_30d": self.get_trends(30),
        }

    # ── 便捷调用 ──────────────────────────────────────────

    def record_crawl_ok(self, latency_ms: float):
        self.record_crawl(success=True, latency_ms=latency_ms)

    def record_crawl_fail(self, latency_ms: float = 0):
        self.record_crawl(success=False, latency_ms=latency_ms)


# ── 全局单例 ─────────────────────────────────────────────
_health_monitor: Optional[HealthMonitorService] = None


def get_health_monitor() -> HealthMonitorService:
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitorService()
    return _health_monitor
