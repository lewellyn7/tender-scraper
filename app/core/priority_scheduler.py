"""
动态优先级调度引擎 - 智能调整采集任务优先级和执行时机

功能：
1. TenderScorer: 多维度评分（预算/截止时间/关键词/成功率/来源可靠性）
2. PriorityQueue: 基于优先级的任务队列
3. AdaptiveScheduler: 自适应采集间隔（根据成功率/负载动态调整）
"""

import time
from collections import deque
import os
import redis.asyncio as redis
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


class SafetyLevel(Enum):
    """采集源安全级别"""
    OFFICIAL_GOV = "official_gov"    # 政府官方（ccgp, ggzy）
    AUTHORIZED = "authorized"         # 授权平台
    THIRD_PARTY = "third_party"      # 第三方平台
    UNKNOWN = "unknown"


# ── Tender Scoring ────────────────────────────────────────────


@dataclass
class TenderScore:
    """招标信息评分"""
    url: str
    title: str
    total_score: float          # 综合评分 0-100
    budget_score: float        # 预算评分 0-25
    urgency_score: float        # 紧迫性评分 0-25
    relevance_score: float      # 关键词相关性 0-25
    reliability_score: float    # 来源可靠性 0-25
    source: SafetyLevel = SafetyLevel.UNKNOWN
    budget: str = ""
    deadline: Optional[datetime] = None
    keywords_matched: List[str] = field(default_factory=list)

    @property
    def priority_level(self) -> str:
        """优先级等级标签"""
        if self.total_score >= 80:
            return "P0-紧急"
        elif self.total_score >= 60:
            return "P1-高"
        elif self.total_score >= 40:
            return "P2-中"
        else:
            return "P3-低"


class TenderScorer:
    """招标信息多维度评分器"""

    # 关键词配置（可热更新）
    KEYWORD_WEIGHTS = {
        # 高价值关键词
        "高优先级": {
            "智慧城市": 5, "数字化": 4, "AI": 4, "大数据": 4,
            "基础设施": 3, "新能源": 3, "医疗设备": 3, "教育": 3,
        },
        # 采购类型
        "采购类型": {
            "服务": 2, "货物": 1, "工程": 2,
        },
    }

    # 预算档位（万元）
    BUDGET_TIERS = [
        (10000, 25, "亿级"),    # 1亿以上: 25分
        (1000, 20, "千万级"),   # 1000万-1亿: 20分
        (500, 15, "百万级"),    # 500万-1000万: 15分
        (100, 10, "小微"),     # 100万-500万: 10分
        (0, 5, "未公示"),      # <100万或未公示: 5分
    ]

    # 来源可靠性得分
    SOURCE_SCORES = {
        SafetyLevel.OFFICIAL_GOV: 25,
        SafetyLevel.AUTHORIZED: 18,
        SafetyLevel.THIRD_PARTY: 10,
        SafetyLevel.UNKNOWN: 5,
    }

    # 紧迫性截止天数阈值
    URGENCY_DAYS = [3, 7, 14, 30]   # 3天内/7天内/14天内/30天内

    def __init__(self, custom_keywords: Optional[Dict[str, Dict[str, int]]] = None):
        if custom_keywords:
            self.KEYWORD_WEIGHTS.update(custom_keywords)

    def score(self, tender: Dict[str, Any]) -> TenderScore:
        """对单条招标信息评分"""
        url = tender.get("url", "")
        title = tender.get("title", "")
        budget_str = tender.get("budget", "")
        publish_date_str = tender.get("publish_date", "")
        source_url = tender.get("source_url", "")

        # 1. 预算评分
        budget_score = self._score_budget(budget_str)

        # 2. 紧迫性评分
        urgency_score = self._score_urgency(publish_date_str)

        # 3. 关键词相关性
        relevance_score, keywords_matched = self._score_keywords(title)

        # 4. 来源可靠性
        reliability_score, source_level = self._score_source(source_url)

        total = budget_score + urgency_score + relevance_score + reliability_score

        return TenderScore(
            url=url,
            title=title,
            total_score=min(total, 100),
            budget_score=budget_score,
            urgency_score=urgency_score,
            relevance_score=relevance_score,
            reliability_score=reliability_score,
            source=source_level,
            budget=budget_str,
            keywords_matched=keywords_matched,
        )

    def _score_budget(self, budget_str: str) -> float:
        """从预算字符串提取金额并评分"""
        if not budget_str:
            return 5.0  # 未公示

        import re
        # 提取数字（万元）
        match = re.search(r'([\d,，.]+)\s*(?:万)?\s*元?', budget_str)
        if not match:
            return 5.0

        try:
            amount = float(re.sub(r'[^\d.]', '', match.group(1)))
            # 判断单位：是否是"元"结尾（实际是元而不是万元）
            if '元' in budget_str and amount < 10000:
                amount *= 10000  # 转换为万元
            elif amount < 100:  # 假设输入已经是万
                amount *= 10000

            for threshold, score, label in self.BUDGET_TIERS:
                if amount >= threshold:
                    return score
            return 5.0
        except (ValueError, Exception):
            return 5.0

    def _score_urgency(self, publish_date_str: str) -> float:
        """根据发布日期计算紧迫性评分"""
        if not publish_date_str:
            return 5.0

        try:
            # 支持多种日期格式
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"):
                try:
                    publish_date = datetime.strptime(publish_date_str[:10], fmt)
                    break
                except ValueError:
                    continue
            else:
                return 5.0

            days_old = (datetime.now() - publish_date).days

            if days_old <= 3:
                return 25.0   # 3天内：最紧迫
            elif days_old <= 7:
                return 20.0
            elif days_old <= 14:
                return 15.0
            elif days_old <= 30:
                return 10.0
            else:
                return 5.0
        except Exception:
            return 5.0

    def _score_keywords(self, title: str) -> tuple[float, List[str]]:
        """关键词命中评分"""
        if not title:
            return 5.0, []

        title_lower = title
        matched = []
        score = 0.0

        for category, keywords in self.KEYWORD_WEIGHTS.items():
            for kw, weight in keywords.items():
                if kw in title_lower:
                    matched.append(kw)
                    score += weight

        # 有匹配则基础分10，否则10（无关键词也可能有价值）
        return min(score + 10, 25), matched

    def _score_source(self, source_url: str) -> tuple[float, SafetyLevel]:
        """来源可靠性评分"""
        if not source_url:
            return 5.0, SafetyLevel.UNKNOWN

        url_lower = source_url.lower()

        if any(k in url_lower for k in ["ccgp", "gov.cn", "ggzy", "cqggzy", "公共资源", "政府采购"]):
            return self.SOURCE_SCORES[SafetyLevel.OFFICIAL_GOV], SafetyLevel.OFFICIAL_GOV
        elif any(k in url_lower for k in ["bidding", "ctex", "chinabidding"]):
            return self.SOURCE_SCORES[SafetyLevel.AUTHORIZED], SafetyLevel.AUTHORIZED
        elif any(k in url_lower for k in ["sina", "sohu", "163", "baidu"]):
            return self.SOURCE_SCORES[SafetyLevel.THIRD_PARTY], SafetyLevel.THIRD_PARTY
        else:
            return 5.0, SafetyLevel.UNKNOWN


# ── Priority Queue ───────────────────────────────────────────


class PriorityQueue:
    """基于优先级的招标采集队列"""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._redis_url = os.getenv("REDIS_URL", "redis://:YOUR_REDIS_PASSWORD_HERE@localhost:6381/0")
        self._redis_key = "tender:scheduler:seen_urls"
        self._redis_ttl = 86400 * 7  # 7 天过期
        self._queue: List[TenderScore] = []
        self._seen_urls: set = set()

    def push(self, tender: Dict[str, Any], scorer: TenderScorer) -> bool:
        """入队，返回是否成功（去重）"""
        url = tender.get("url", "")
        if not url or url in self._seen_urls:
            return False

        score = scorer.score(tender)

        # 去重
        if url in self._seen_urls:
            return False

        self._queue.append(score)
        self._seen_urls.add(url)

        # 维护堆性质：按 total_score 降序
        self._queue.sort(key=lambda x: x.total_score, reverse=True)

        # 限制队列大小
        if len(self._queue) > self.max_size:
            self._queue.pop()

        return True

    def push_batch(self, tenders: List[Dict[str, Any]], scorer: TenderScorer) -> int:
        """批量入队，返回成功入队数量"""
        count = 0
        for t in tenders:
            if self.push(t, scorer):
                count += 1
        return count

    def pop(self) -> Optional[TenderScore]:
        """出队最高优先级"""
        if self._queue:
            return self._queue.pop(0)
        return None

    def pop_all(self, min_score: float = 0) -> List[TenderScore]:
        """出队所有>=最低分数的项"""
        result = [item for item in self._queue if item.total_score >= min_score]
        for item in result:
            self._queue.remove(item)
        return result

    def peek(self, top_n: int = 10) -> List[TenderScore]:
        """查看前N个最高优先级（不出队）"""
        return self._queue[:top_n]

    def stats(self) -> Dict[str, Any]:
        """队列统计"""
        if not self._queue:
            return {"total": 0, "by_priority": {}}

        scores = [s.total_score for s in self._queue]
        priorities = {}
        for s in self._queue:
            p = s.priority_level
            priorities[p] = priorities.get(p, 0) + 1

        return {
            "total": len(self._queue),
            "avg_score": sum(scores) / len(scores),
            "max_score": max(scores),
            "min_score": min(scores),
            "by_priority": priorities,
        }

    def clear(self):
        self._queue.clear()
        self._seen_urls.clear()


# ── Adaptive Scheduler ────────────────────────────────────────


@dataclass
class SchedulerMetrics:
    """调度器运行时指标"""
    total_runs: int = 0
    successful_collections: int = 0
    failed_collections: int = 0
    avg_duration_ms: float = 0.0
    last_run_at: Optional[datetime] = None
    recent_errors: deque = field(default_factory=lambda: deque(maxlen=20))

    @property
    def success_rate(self) -> float:
        total = self.successful_collections + self.failed_collections
        return self.successful_collections / total if total > 0 else 0.0

    @property
    def health_status(self) -> str:
        rate = self.success_rate
        if rate >= 0.9:
            return "healthy"
        elif rate >= 0.7:
            return "degraded"
        elif self.total_runs > 0:
            return "unhealthy"
        return "idle"


class AdaptiveScheduler:
    """
    自适应采集调度器

    核心逻辑：
    1. 根据成功率动态调整采集间隔
    2. 成功率 > 90% → 加快采集（缩短间隔）
    3. 成功率 < 70% → 减慢采集（延长间隔，保护目标站点）
    4. 连续失败 → 进入退避模式
    """

    # 间隔档位（秒）
    INTERVAL_TIERS = [
        (0.9, 60 * 5, "fast", "快速（5分钟）"),
        (0.7, 60 * 15, "normal", "正常（15分钟）"),
        (0.5, 60 * 30, "slow", "慢速（30分钟）"),
        (0.0, 60 * 60, "backoff", "退避（60分钟）"),
    ]

    def __init__(
        self,
        initial_interval: int = 60 * 15,  # 默认15分钟
        min_interval: int = 60 * 5,         # 最小5分钟
        max_interval: int = 60 * 60,         # 最大60分钟
    ):
        self.current_interval = initial_interval
        self.min_interval = min_interval
        self.max_interval = max_interval
        self._mode = "normal"
        self._consecutive_failures = 0
        self.metrics = SchedulerMetrics()

    def record_run(self, success: bool, duration_ms: float, error: Optional[str] = None):
        """记录一次采集运行结果"""
        self.metrics.total_runs += 1
        self.metrics.avg_duration_ms = (
            (self.metrics.avg_duration_ms * (self.metrics.total_runs - 1) + duration_ms)
            / self.metrics.total_runs
        )
        self.metrics.last_run_at = datetime.now()

        if success:
            self.metrics.successful_collections += 1
            self._consecutive_failures = 0
            self._adjust_interval()
        else:
            self.metrics.failed_collections += 1
            self._consecutive_failures += 1
            if error:
                self.metrics.recent_errors.append({
                    "time": datetime.now().isoformat(),
                    "error": error[:100],
                })
            self._adjust_interval()

    def _adjust_interval(self):
        """根据当前指标调整采集间隔"""
        rate = self.metrics.success_rate
        failures = self._consecutive_failures

        # 连续失败 > 3 → 直接退避
        if failures >= 3:
            self.current_interval = self.max_interval
            self._mode = "backoff"
            logger.warning(
                f"[AdaptiveScheduler] 连续{failures}次失败，"
                f"进入退避模式，间隔 {self.current_interval}秒"
            )
            return

        # 根据成功率调整
        for threshold, interval, mode_name, label in self.INTERVAL_TIERS:
            if rate >= threshold:
                if interval != self.current_interval:
                    logger.info(
                        f"[AdaptiveScheduler] 成功率 {rate:.1%} → 切换到{label}，"
                        f"间隔 {interval}秒"
                    )
                self.current_interval = interval
                self._mode = mode_name
                return

    @property
    def next_run_in(self) -> Optional[float]:
        """距离下次运行的预估秒数"""
        if not self.metrics.last_run_at:
            return None
        elapsed = (datetime.now() - self.metrics.last_run_at).total_seconds()
        return max(0, self.current_interval - elapsed)

    def get_status(self) -> Dict[str, Any]:
        """获取调度器状态摘要"""
        return {
            "mode": self._mode,
            "interval_seconds": self.current_interval,
            "interval_formatted": f"{self.current_interval // 60}分钟",
            "success_rate": f"{self.metrics.success_rate:.1%}",
            "health": self.metrics.health_status,
            "total_runs": self.metrics.total_runs,
            "consecutive_failures": self._consecutive_failures,
            "next_run_in_seconds": round(self.next_run_in or 0, 1),
        }


# ── Priority Crawler ────────────────────────────────────────


class PriorityCrawler:
    """
    优先级驱动的采集器

    使用 TenderScorer 对待采集内容评分，
    按优先级从高到低采集，
    由 AdaptiveScheduler 控制采集节奏。
    """

    def __init__(
        self,
        scorer: Optional[TenderScorer] = None,
        scheduler: Optional[AdaptiveScheduler] = None,
        priority_queue: Optional[PriorityQueue] = None,
    ):
        self.scorer = scorer or TenderScorer()
        self.scheduler = scheduler or AdaptiveScheduler()
        self.queue = priority_queue or PriorityQueue()

    def add_tenders(self, tenders: List[Dict[str, Any]]) -> int:
        """批量添加招标信息到优先队列"""
        count = self.queue.push_batch(tenders, self.scorer)
        logger.debug(
            f"[PriorityCrawler] 入队 {count}/{len(tenders)} 条，"
            f"队列状态: {self.queue.stats()}"
        )
        return count

    def get_next_batch(self, batch_size: int = 20, min_score: float = 0) -> List[TenderScore]:
        """获取下一批待采集项（按优先级）"""
        return self.queue.pop_all(min_score=min_score)[:batch_size]

    def get_collection_plan(self) -> Dict[str, Any]:
        """获取当前采集计划（不执行）"""
        top = self.queue.peek(top_n=10)
        return {
            "scheduler_status": self.scheduler.get_status(),
            "queue_stats": self.queue.stats(),
            "top_10_priorities": [
                {
                    "title": s.title[:50],
                    "url": s.url,
                    "score": round(s.total_score, 1),
                    "level": s.priority_level,
                    "budget": s.budget,
                }
                for s in top
            ],
        }
