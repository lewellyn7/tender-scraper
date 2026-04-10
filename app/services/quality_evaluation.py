#!/usr/bin/env python3
"""
QualityEvaluationService - 采集质量评估服务
对单条采集结果进行多维度质量评分（0-100）
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class QualityScore:
    """质量评分结果"""
    total: float           # 总分 0-100
    completeness: float     # 完整性（内容长度、字段填充率）
    freshness: float       # 时效性（发布/截止时间）
    accuracy: float        # 准确性（金额格式、日期格式）
    richness: float        # 丰富度（附件数量、联系方式）
    issues: List[str]      # 问题列表


class QualityEvaluationService:
    """采集质量评估器"""

    # 各维度权重
    WEIGHTS = {
        "completeness": 0.35,
        "freshness": 0.25,
        "accuracy": 0.20,
        "richness": 0.20,
    }

    def __init__(self):
        self._history: List[QualityScore] = []
        self._avg_scores: Dict[str, float] = {}

    def evaluate(self, tender: dict) -> QualityScore:
        """
        评估单条招标记录的质量（所有维度归一化到 0-100）

        Args:
            tender: dict，应包含 title/content_preview/full_content/
                   budget/deadline/contact_info/attachments/publish_date 等字段

        Returns:
            QualityScore: 多维度质量评分（0-100）
        """
        title = tender.get("title", "")
        content = tender.get("full_content", "") or tender.get("content_preview", "") or ""
        budget = tender.get("budget", "")
        deadline = tender.get("submission_deadline", "") or tender.get("deadline", "")
        contact = tender.get("contact_info", "")
        attachments = tender.get("attachments", [])
        publish_date = tender.get("publish_date", "") or tender.get("created_at", "")

        # 1. 完整性（归一化到 0-100）
        completeness = self._score_completeness(title, content, budget, deadline, contact)
        completeness_pct = completeness / 35.0 * 100

        # 2. 时效性（归一化到 0-100）
        freshness = self._score_freshness(publish_date, deadline)
        freshness_pct = freshness / 25.0 * 100

        # 3. 准确性（归一化到 0-100）
        accuracy = self._score_accuracy(budget, deadline, title, content)
        accuracy_pct = accuracy / 20.0 * 100

        # 4. 丰富度（归一化到 0-100）
        richness = self._score_richness(contact, attachments, content)
        richness_pct = richness / 20.0 * 100

        # 加权总分（0-100）
        total = (
            completeness_pct * self.WEIGHTS["completeness"]
            + freshness_pct * self.WEIGHTS["freshness"]
            + accuracy_pct * self.WEIGHTS["accuracy"]
            + richness_pct * self.WEIGHTS["richness"]
        )
        total = round(min(100, total), 2)

        # 问题收集
        issues = []
        if completeness_pct < 60:
            issues.append("内容完整度不足")
        if freshness_pct < 50:
            issues.append("时效性较差（无有效截止时间）")
        if accuracy_pct < 60:
            issues.append("信息准确性存疑")
        if richness_pct < 40:
            issues.append("信息丰富度低（缺少联系方式/附件）")
        if not title or len(title) < 10:
            issues.append("标题过短或缺失")

        score = QualityScore(
            total=total,
            completeness=round(completeness_pct, 2),
            freshness=round(freshness_pct, 2),
            accuracy=round(accuracy_pct, 2),
            richness=round(richness_pct, 2),
            issues=issues,
        )

        self._history.append(score)
        self._update_avg()
        return score

    def _score_completeness(
        self, title: str, content: str, budget: str, deadline: str, contact: str
    ) -> float:
        """完整性（满分35分）"""
        score = 0.0
        # 标题（满分10）
        if title and len(title) >= 10:
            score += 10
        elif title:
            score += len(title) / 2
        # 内容长度（满分15）
        content_len = len(content) if content else 0
        if content_len >= 2000:
            score += 15
        elif content_len >= 1000:
            score += 12
        elif content_len >= 500:
            score += 8
        elif content_len >= 200:
            score += 4
        elif content_len > 0:
            score += 2
        # 预算字段（满分5）
        if budget and self._has_budget_format(budget):
            score += 5
        elif budget:
            score += 2
        # 截止时间（满分5）
        if deadline and self._has_date_format(deadline):
            score += 5
        elif deadline:
            score += 2
        return min(35, score)

    def _score_freshness(self, publish_date: str, deadline: str) -> float:
        """时效性（满分25分）"""
        score = 0.0
        if publish_date and self._has_date_format(publish_date):
            score += 10
        if deadline and self._has_date_format(deadline):
            score += 15
        return min(25, score)

    def _score_accuracy(self, budget: str, deadline: str, title: str, content: str) -> float:
        """准确性（满分20分）"""
        score = 15.0  # 基础分
        if budget:
            if not self._has_budget_format(budget) and not self._looks_like_valid_budget(budget):
                score -= 5
        if deadline and not self._has_date_format(deadline):
            score -= 3
        if title and content:
            overlap = len(set(title) & set(content)) / max(len(set(title)), 1)
            if overlap < 0.05 and len(content) > 100:
                score -= 5
        return max(0, min(20, score))

    def _score_richness(self, contact: str, attachments, content: str) -> float:
        """丰富度（满分20分）"""
        score = 0.0
        # 联系方式（满分8）
        if contact:
            parts = [p for p in contact.replace("，", ";").split(";") if p.strip()]
            score += min(8, len(parts) * 4)
        # 附件数量（满分7）
        attach_count = len(attachments) if attachments else 0
        if attach_count >= 3:
            score += 7
        elif attach_count >= 1:
            score += 4
        # 内容段落（满分5）
        if content:
            paragraphs = [p for p in content.split("\n") if p.strip()]
            if len(paragraphs) >= 10:
                score += 5
            elif len(paragraphs) >= 5:
                score += 3
            elif paragraphs:
                score += 1
        return min(20, score)

    # ── 辅助方法 ──────────────────────────────────────────

    def _has_budget_format(self, text: str) -> bool:
        """判断是否包含有效金额格式"""
        return bool(re.search(r"[\d,.，.]+\s*(?:万元|万|元|万元整)", text))

    def _has_date_format(self, text: str) -> bool:
        """判断是否包含有效日期格式"""
        return bool(re.search(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?", text))

    def _looks_like_valid_budget(self, text: str) -> bool:
        """判断是否像有效金额"""
        return bool(re.search(r"\d", text)) and not text.strip().isdigit()

    def _update_avg(self):
        """更新历史平均分"""
        if not self._history:
            return
        n = len(self._history)
        self._avg_scores = {
            "total": sum(s.total for s in self._history) / n,
            "completeness": sum(s.completeness for s in self._history) / n,
            "freshness": sum(s.freshness for s in self._history) / n,
            "accuracy": sum(s.accuracy for s in self._history) / n,
            "richness": sum(s.richness for s in self._history) / n,
        }

    def get_avg_scores(self) -> Dict[str, float]:
        """获取历史平均分"""
        return self._avg_scores.copy()

    def get_history(self, limit: int = 100) -> List[QualityScore]:
        """获取最近 N 条评分记录"""
        return self._history[-limit:]

    def get_quality_distribution(self) -> Dict[str, int]:
        """获取质量分布统计"""
        dist = {"excellent": 0, "good": 0, "fair": 0, "poor": 0}
        for s in self._history:
            if s.total >= 80:
                dist["excellent"] += 1
            elif s.total >= 60:
                dist["good"] += 1
            elif s.total >= 40:
                dist["fair"] += 1
            else:
                dist["poor"] += 1
        return dist
