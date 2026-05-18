#!/usr/bin/env python3
"""
智能推荐系统服务 - 基于 PostgreSQL 数据
- 推荐相关采购项目
- 关键词优化建议
"""
import json
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from loguru import logger
from app.utils.tfidf_matcher import TFIDFMatcher

class RecommendationService:
    """智能推荐服务"""
    
    def __init__(self):
        self._cache = {"data": None, "timestamp": 0, "ttl": 300}  # 5 分钟缓存
    
    def _load_projects(self) -> List[Dict]:
        """从 PostgreSQL 加载项目数据（带缓存）"""
        now = time.time()
        if self._cache["data"] and (now - self._cache["timestamp"]) < self._cache["ttl"]:
            return self._cache["data"]
        
        try:
            from app.database import get_db
            db = get_db()
            conn = db._get_conn()
            
            projects = []
            for table in ("projects_cqggzy", "projects_ccgp"):
                try:
                    rows = conn.execute(f'SELECT title, category, tender_type, business_type, info_type, publish_date, budget, bid_amount, deadline, region, industry, project_overview, bidder_requirements, submission_deadline, contact_name, contact_phone, keywords_matched, source_url, url, scraped_at FROM {table}').fetchall()
                    for row in rows:
                        projects.append({
                            "title": row[0] or "",
                            "category": row[1] or "",
                            "tender_type": row[2] or "",
                            "business_type": row[3] or "",
                            "info_type": row[4] or "",
                            "publish_date": str(row[5]) if row[5] else "",
                            "budget": row[6] or "",
                            "bid_amount": row[7] or "",
                            "deadline": str(row[8]) if row[8] else "",
                            "region": row[9] or "",
                            "industry": row[10] or "",
                            "project_overview": row[11] or "",
                            "bidder_requirements": row[12] or "",
                            "submission_deadline": row[13] or "",
                            "contact_name": row[14] or "",
                            "contact_phone": row[15] or "",
                            "keywords_matched": row[16] or "",
                            "source_url": row[17] or "",
                            "url": row[18] or "",
                            "scraped_at": str(row[19]) if row[19] else "",
                        })
                except Exception as e:
                    logger.warning(f"Failed to load from {table}: {e}")
            
            self._cache["data"] = projects
            self._cache["timestamp"] = now
            return projects
        except Exception as e:
            logger.warning(f"Failed to load projects for recommendation: {e}")
            return []
    
    def _extract_keywords(self, text: str) -> List[str]:
        """提取文本中的关键词"""
        if not text:
            return []
        stopwords = {"的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个"}
        words = re.findall(r"[\u4e00-\u9fa5]{2,4}", text)
        filtered = [w for w in words if w not in stopwords]
        return filtered
    
    def analyze_historical_data(self) -> Dict:
        """分析历史采集数据"""
        projects = self._load_projects()
        if not projects:
            return {"error": "No data available"}
        
        date_dist = Counter()
        source_dist = Counter()
        region_dist = Counter()
        industry_dist = Counter()
        keyword_freq = Counter()
        budget_values = []
        
        for p in projects:
            pub_date = p.get("publish_date", "")
            if pub_date:
                date_dist[pub_date[:7]] += 1
            
            source = p.get("source_url", "")
            if source:
                source_match = re.search(r"//([^/]+)", source)
                if source_match:
                    source_dist[source_match.group(1)] += 1
            
            region = p.get("region", "")
            if region:
                region_dist[region] += 1
            
            industry = p.get("industry", "")
            if industry:
                industry_dist[industry] += 1
            
            keywords = p.get("keywords_matched", "")
            if isinstance(keywords, str):
                keywords = [k.strip() for k in keywords.split(",") if k.strip()]
                for kw in keywords:
                    keyword_freq[kw] += 1
            
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
        """基于用户关键词推荐相关项目"""
        projects = self._load_projects()
        if not projects or not user_keywords:
            return []
        
        recommendations = []
        if use_tfidf:
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
            for p in projects:
                title = p.get("title", "").lower()
                content = p.get("project_overview", "").lower()
                matched = [kw for kw in user_keywords if kw.lower() in title or kw.lower() in content]
                if matched:
                    score = len(matched) / len(user_keywords)
                    recommendations.append({
                        "project": p,
                        "score": score,
                        "matched_keywords": matched,
                        "match_rate": score,
                    })
        
        recommendations.sort(key=lambda x: x["score"], reverse=True)
        return recommendations[:limit]
    
    def suggest_keywords(self, context: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """关键词优化建议"""
        projects = self._load_projects()
        if not projects:
            return []
        
        keyword_stats = defaultdict(lambda: {"count": 0, "projects": []})
        for p in projects:
            keywords = p.get("keywords_matched", "")
            if isinstance(keywords, str):
                keywords = [k.strip() for k in keywords.split(",") if k.strip()]
                for kw in keywords:
                    keyword_stats[kw]["count"] += 1
                    keyword_stats[kw]["projects"].append(p.get("url", ""))
        
        if not context:
            sorted_keywords = sorted(keyword_stats.items(), key=lambda x: x[1]["count"], reverse=True)
            return [
                {
                    "keyword": kw,
                    "frequency": stats["count"],
                    "project_count": len(set(stats["projects"])),
                    "relevance_score": stats["count"],
                }
                for kw, stats in sorted_keywords[:limit]
            ]
        
        context_keywords = self._extract_keywords(context)
        context_vector = Counter(context_keywords)
        suggestions = []
        
        for kw, stats in keyword_stats.items():
            kw_keywords = self._extract_keywords(kw)
            if not kw_keywords:
                continue
            
            kw_vector = Counter(kw_keywords)
            intersection = set(context_vector.keys()) & set(kw_vector.keys())
            if not intersection:
                continue
            
            dot_product = sum(context_vector[k] * kw_vector[k] for k in intersection)
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
        
        suggestions.sort(key=lambda x: x["relevance_score"], reverse=True)
        return suggestions[:limit]
    
    def get_similar_projects(self, project_url: str, limit: int = 5) -> List[Dict]:
        """获取与指定项目相似的其他项目"""
        projects = self._load_projects()
        if not projects:
            return []
        
        reference = None
        for p in projects:
            if p.get("url") == project_url:
                reference = p
                break
        
        if not reference:
            return []
        
        ref_keywords = set()
        title = reference.get("title", "")
        ref_keywords.update(self._extract_keywords(title))
        keywords_matched = reference.get("keywords_matched", "")
        if isinstance(keywords_matched, str):
            keywords_matched = [k.strip() for k in keywords_matched.split(",") if k.strip()]
            ref_keywords.update(keywords_matched)
        
        similarities = []
        for p in projects:
            if p.get("url") == project_url:
                continue
            
            p_keywords = set()
            p_title = p.get("title", "")
            p_keywords.update(self._extract_keywords(p_title))
            p_keywords_matched = p.get("keywords_matched", "")
            if isinstance(p_keywords_matched, str):
                p_keywords_matched = [k.strip() for k in p_keywords_matched.split(",") if k.strip()]
                p_keywords.update(p_keywords_matched)
            
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
        
        similarities.sort(key=lambda x: x["similarity"], reverse=True)
        return similarities[:limit]
    
    def get_trending_keywords(self, days: int = 7, limit: int = 10) -> List[Dict]:
        """获取近期热门关键词（趋势分析）"""
        projects = self._load_projects()
        if not projects:
            return []
        
        now = datetime.now()
        cutoff = now - timedelta(days=days)
        
        recent_keywords = Counter()
        older_keywords = Counter()
        
        for p in projects:
            keywords = p.get("keywords_matched", "")
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
        
        trending = []
        all_keywords = set(recent_keywords.keys()) | set(older_keywords.keys())
        
        for kw in all_keywords:
            recent_count = recent_keywords.get(kw, 0)
            older_count = older_keywords.get(kw, 0)
            trend_score = recent_count / (older_count + 1) if recent_count > 0 else 0
            
            if recent_count > 0:
                trending.append({
                    "keyword": kw,
                    "recent_count": recent_count,
                    "older_count": older_count,
                    "trend_score": trend_score,
                    "is_rising": trend_score > 1.5,
                })
        
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
