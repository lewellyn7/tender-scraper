#!/usr/bin/env python3
"""
智能推荐系统服务
- 基于历史采集数据分析
- 推荐相关采购项目
- 关键词优化建议
"""

import json
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger

from app.database.async_models import DatabaseManager
from app.utils.tfidf_matcher import TFIDFMatcher

SYS_PATH = Path(__file__).parent.parent.parent


class RecommendationService:
    """智能推荐服务"""

    def __init__(self):
        self._cache = {"data": None, "timestamp": 0, "ttl": 300}  # 5 分钟缓存

    def _load_projects(self) -> List[Dict]:
        """加载项目数据（带缓存）"""
        now = time.time()
        if self._cache["data"] and (now - self._cache["timestamp"]) < self._cache["ttl"]:
            return self._cache["data"]

        data_file = SYS_PATH / "output" / "latest.json"
        projects = []
        if data_file.exists():
            try:
                with open(data_file, encoding="utf-8") as f:
                    d = json.load(f)
                    projects = d.get("projects", [])
                self._cache["data"] = projects
                self._cache["timestamp"] = now
            except Exception as e:
                logger.warning(f"Failed to load projects for recommendation: {e}")
        return projects

    def _extract_keywords(self, text: str) -> List[str]:
        """提取文本中的关键词"""
        if not text:
            return []
        # 移除常见停用词
        stopwords = {"的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个"}
        # 提取 2-4 字词语
        words = re.findall(r"[\u4e00-\u9fa5]{2,4}", text)
        # 过滤停用词并统计
        filtered = [w for w in words if w not in stopwords]
        return filtered

    def analyze_historical_data(self) -> Dict:
        """
        分析历史采集数据
        返回：统计摘要、趋势、模式
        """
        projects = self._load_projects()
        if not projects:
            return {"error": "No data available"}

        # 时间分布
        date_dist = Counter()
        # 来源分布
        source_dist = Counter()
        # 地区分布
        region_dist = Counter()
        # 行业分布
        industry_dist = Counter()
        # 关键词频率
        keyword_freq = Counter()
        # 金额分布
        budget_values = []

        for p in projects:
            # 日期
            pub_date = p.get("publish_date", "")
            if pub_date:
                date_dist[pub_date[:7]] += 1  # YYYY-MM

            # 来源
            source = p.get("source_url", "")
            if source:
                source_match = re.search(r"//([^/]+)", source)
                if source_match:
                    source_dist[source_match.group(1)] += 1

            # 地区
            region = p.get("region", "")
            if region:
                region_dist[region] += 1

            # 行业
            industry = p.get("industry", "")
            if industry:
                industry_dist[industry] += 1

            # 关键词
            keywords = p.get("keywords_matched", [])
            if isinstance(keywords, str):
                keywords = [k.strip() for k in keywords.split(",") if k.strip()]
            for kw in keywords:
                keyword_freq[kw] += 1

            # 预算
            budget = p.get("budget", "")
            if budget:
                match = re.search(r"[\d,]+\.?\d*", budget.replace(",", ""))
                if match:
                    try:
                        val = float(match.group())
                        if "万" in budget:
                            val *= 10000
                        elif "亿" in budget:
                            val *= 100000000
                        budget_values.append(val)
                    except ValueError:
                        pass

        total = len(projects)
        avg_budget = sum(budget_values) / len(budget_values) if budget_values else 0

        return {
            "total_projects": total,
            "date_distribution": dict(date_dist.most_common(12)),
            "source_distribution": dict(source_dist.most_common(10)),
            "region_distribution": dict(region_dist.most_common(10)),
            "industry_distribution": dict(industry_dist.most_common(10)),
            "top_keywords": dict(keyword_freq.most_common(20)),
            "avg_budget": avg_budget,
            "budget_range": {
                "min": min(budget_values) if budget_values else 0,
                "max": max(budget_values) if budget_values else 0,
            },
        }

    def recommend_projects(
        self,
        user_keywords: List[str],
        limit: int = 10,
        use_tfidf: bool = True,
    ) -> List[Dict]:
        """
        基于用户关键词推荐相关项目

        Args:
            user_keywords: 用户关注的关键词列表
            limit: 返回数量限制
            use_tfidf: 是否使用 TF-IDF 算法

        Returns:
            推荐的项目列表（按相关性排序）
        """
        projects = self._load_projects()
        if not projects or not user_keywords:
            return []

        recommendations = []

        if use_tfidf:
            # 使用 TF-IDF 匹配
            matcher = TFIDFMatcher()
            titles = [p.get("title", "") for p in projects]
            matcher.build_corpus(titles)
            matcher.build_keywords(user_keywords)

            for i, p in enumerate(projects):
                title = p.get("title", "")
                score, matched, _ = matcher.match(title, user_keywords)
                if matched:
                    recommendations.append({
                        "project": p,
                        "score": score,
                        "matched_keywords": matched,
                        "match_rate": len(matched) / len(user_keywords) if user_keywords else 0,
                    })
        else:
            # 简单关键词匹配
            for p in projects:
                title = p.get("title", "").lower()
                content = p.get("content_preview", "").lower()
                matched = [
                    kw
                    for kw in user_keywords
                    if kw.lower() in title or kw.lower() in content
                ]
                if matched:
                    score = len(matched) / len(user_keywords)
                    recommendations.append({
                        "project": p,
                        "score": score,
                        "matched_keywords": matched,
                        "match_rate": score,
                    })

        # 按分数排序
        recommendations.sort(key=lambda x: x["score"], reverse=True)
        return recommendations[:limit]

    def suggest_keywords(self, context: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """
        关键词优化建议

        Args:
            context: 上下文（可选），用于生成更精准的 sugerencias
            limit: 返回数量限制

        Returns:
            推荐关键词列表（带频率、相关性评分）
        """
        projects = self._load_projects()
        if not projects:
            return []

        # 统计所有关键词频率
        keyword_stats = defaultdict(lambda: {"count": 0, "projects": []})

        for p in projects:
            keywords = p.get("keywords_matched", [])
            if isinstance(keywords, str):
                keywords = [k.strip() for k in keywords.split(",") if k.strip()]

            for kw in keywords:
                keyword_stats[kw]["count"] += 1
                keyword_stats[kw]["projects"].append(p.get("url", ""))

        # 如果没有上下文，返回高频关键词
        if not context:
            sorted_keywords = sorted(
                keyword_stats.items(), key=lambda x: x[1]["count"], reverse=True
            )
            return [
                {
                    "keyword": kw,
                    "frequency": stats["count"],
                    "project_count": len(set(stats["projects"])),
                    "relevance_score": stats["count"],  # 简单用频率作为相关性
                }
                for kw, stats in sorted_keywords[:limit]
            ]

        # 有上下文时，计算与上下文的相关性
        context_keywords = self._extract_keywords(context)
        context_vector = Counter(context_keywords)

        suggestions = []
        for kw, stats in keyword_stats.items():
            # 计算与上下文的相关性（简单重叠度）
            kw_keywords = self._extract_keywords(kw)
            if not kw_keywords:
                continue

            kw_vector = Counter(kw_keywords)
            # 余弦相似度
            intersection = set(context_vector.keys()) & set(kw_vector.keys())
            if not intersection:
                continue

            dot_product = sum(
                context_vector[k] * kw_vector[k] for k in intersection
            )
            norm_context = sum(v**2 for v in context_vector.values()) ** 0.5
            norm_kw = sum(v**2 for v in kw_vector.values()) ** 0.5

            if norm_context * norm_kw == 0:
                continue

            similarity = dot_product / (norm_context * norm_kw)

            suggestions.append({
                "keyword": kw,
                "frequency": stats["count"],
                "project_count": len(set(stats["projects"])),
                "relevance_score": similarity,
                "context_match": list(intersection),
            })

        # 按相关性排序
        suggestions.sort(key=lambda x: x["relevance_score"], reverse=True)
        return suggestions[:limit]

    def get_similar_projects(self, project_url: str, limit: int = 5) -> List[Dict]:
        """
        获取与指定项目相似的其他项目

        Args:
            project_url: 参考项目 URL
            limit: 返回数量限制

        Returns:
            相似项目列表
        """
        projects = self._load_projects()
        if not projects:
            return []

        # 找到参考项目
        reference = None
        for p in projects:
            if p.get("url") == project_url:
                reference = p
                break

        if not reference:
            return []

        # 提取参考项目的特征
        ref_keywords = set()
        title = reference.get("title", "")
        ref_keywords.update(self._extract_keywords(title))

        keywords_matched = reference.get("keywords_matched", [])
        if isinstance(keywords_matched, str):
            keywords_matched = [k.strip() for k in keywords_matched.split(",") if k.strip()]
        ref_keywords.update(keywords_matched)

        # 计算相似度
        similarities = []
        for p in projects:
            if p.get("url") == project_url:
                continue

            p_keywords = set()
            p_title = p.get("title", "")
            p_keywords.update(self._extract_keywords(p_title))

            p_keywords_matched = p.get("keywords_matched", [])
            if isinstance(p_keywords_matched, str):
                p_keywords_matched = [
                    k.strip() for k in p_keywords_matched.split(",") if k.strip()
                ]
            p_keywords.update(p_keywords_matched)

            # Jaccard 相似度
            if not ref_keywords or not p_keywords:
                continue

            intersection = ref_keywords & p_keywords
            union = ref_keywords | p_keywords
            similarity = len(intersection) / len(union) if union else 0

            if similarity > 0:
                similarities.append({
                    "project": p,
                    "similarity": similarity,
                    "common_keywords": list(intersection),
                })

        # 按相似度排序
        similarities.sort(key=lambda x: x["similarity"], reverse=True)
        return similarities[:limit]

    def get_trending_keywords(self, days: int = 7, limit: int = 10) -> List[Dict]:
        """
        获取近期热门关键词（趋势分析）

        Args:
            days: 时间范围（天数）
            limit: 返回数量限制

        Returns:
            热门关键词列表（带趋势评分）
        """
        projects = self._load_projects()
        if not projects:
            return []

        now = datetime.now()
        cutoff = now - timedelta(days=days)

        # 按时间分段统计
        recent_keywords = Counter()
        older_keywords = Counter()

        for p in projects:
            keywords = p.get("keywords_matched", [])
            if isinstance(keywords, str):
                keywords = [k.strip() for k in keywords.split(",") if k.strip()]

            pub_date_str = p.get("publish_date", "")
            try:
                pub_date = datetime.strptime(pub_date_str, "%Y-%m-%d")
                if pub_date >= cutoff:
                    for kw in keywords:
                        recent_keywords[kw] += 1
                else:
                    for kw in keywords:
                        older_keywords[kw] += 1
            except (ValueError, TypeError):
                pass

        # 计算趋势分数（近期频率 / 历史频率）
        trending = []
        all_keywords = set(recent_keywords.keys()) | set(older_keywords.keys())

        for kw in all_keywords:
            recent_count = recent_keywords.get(kw, 0)
            older_count = older_keywords.get(kw, 0)

            # 避免除零，给历史计数加 1
            trend_score = recent_count / (older_count + 1)

            if recent_count > 0:
                trending.append({
                    "keyword": kw,
                    "recent_count": recent_count,
                    "older_count": older_count,
                    "trend_score": trend_score,
                    "is_rising": trend_score > 1.5,  # 增长 50% 以上
                })

        # 按趋势分数排序
        trending.sort(key=lambda x: x["trend_score"], reverse=True)
        return trending[:limit]


# 单例
_recommendation_service = None


def get_recommendation_service() -> RecommendationService:
    """获取推荐服务单例"""
    global _recommendation_service
    if _recommendation_service is None:
        _recommendation_service = RecommendationService()
    return _recommendation_service
