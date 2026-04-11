"""
动态优先级调度引擎 API

GET  /api/priority/status          - 调度器状态
GET  /api/priority/plan            - 当前采集计划（top10）
GET  /api/priority/queue/stats     - 队列统计
POST /api/priority/score           - 对单条招标评分
POST /api/priority/add-tenders     - 批量添加招标到队列
POST /api/priority/record          - 记录采集结果（反馈给调度器）
GET  /api/priority/config          - 获取关键词/配置
PUT  /api/priority/config           - 更新关键词/配置
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/priority", tags=["priority"])

# ── 全局单例 ──────────────────────────────────────────────────

_scorer: Optional[Any] = None
_crawler: Optional[Any] = None


def _get_crawler():
    global _scorer, _crawler
    if _crawler is None:
        from app.core.priority_scheduler import AdaptiveScheduler, PriorityCrawler, TenderScorer
        _scorer = TenderScorer()
        _crawler = PriorityCrawler(scorer=_scorer, scheduler=AdaptiveScheduler())
    return _crawler


# ── Request/Response Models ──────────────────────────────────


class ScoreRequest(BaseModel):
    url: str
    title: str
    budget: Optional[str] = ""
    publish_date: Optional[str] = ""
    source_url: Optional[str] = ""


class ScoreResponse(BaseModel):
    url: str
    title: str
    total_score: float
    budget_score: float
    urgency_score: float
    relevance_score: float
    reliability_score: float
    priority_level: str
    keywords_matched: List[str]


class AddTendersRequest(BaseModel):
    tenders: List[Dict[str, Any]]  # [{url, title, budget, publish_date, source_url}, ...]


class AddTendersResponse(BaseModel):
    added: int
    total: int
    queue_stats: Dict[str, Any]


class RecordRequest(BaseModel):
    success: bool
    duration_ms: float
    error: Optional[str] = None


class ConfigUpdateRequest(BaseModel):
    keywords: Optional[Dict[str, Dict[str, int]]] = None  # 热更新关键词


# ── Routes ────────────────────────────────────────────────────


@router.get("/status")
def get_status(user_id: str = Depends(get_current_user)):
    """获取调度器当前状态"""
    crawler = _get_crawler()
    return crawler.scheduler.get_status()


@router.get("/plan")
def get_plan(user_id: str = Depends(get_current_user)):
    """获取当前采集计划（top10 优先级）"""
    crawler = _get_crawler()
    return crawler.get_collection_plan()


@router.get("/queue/stats")
def get_queue_stats(user_id: str = Depends(get_current_user)):
    """获取队列统计"""
    crawler = _get_crawler()
    return crawler.queue.stats()


@router.post("/score")
def score_tender(req: ScoreRequest, user_id: str = Depends(get_current_user)):
    """对单条招标评分"""
    crawler = _get_crawler()
    tender_dict = req.model_dump()
    score = crawler.scorer.score(tender_dict)
    return ScoreResponse(
        url=score.url,
        title=score.title,
        total_score=round(score.total_score, 1),
        budget_score=round(score.budget_score, 1),
        urgency_score=round(score.urgency_score, 1),
        relevance_score=round(score.relevance_score, 1),
        reliability_score=round(score.reliability_score, 1),
        priority_level=score.priority_level,
        keywords_matched=score.keywords_matched,
    )


@router.post("/add-tenders")
def add_tenders(req: AddTendersRequest, user_id: str = Depends(get_current_user)):
    """批量添加招标到优先队列"""
    crawler = _get_crawler()
    added = crawler.add_tenders(req.tenders)
    return AddTendersResponse(
        added=added,
        total=len(req.tenders),
        queue_stats=crawler.queue.stats(),
    )


@router.post("/record")
def record_result(req: RecordRequest, user_id: str = Depends(get_current_user)):
    """记录采集结果（反馈给自适应调度器）"""
    crawler = _get_crawler()
    crawler.scheduler.record_run(
        success=req.success,
        duration_ms=req.duration_ms,
        error=req.error,
    )
    return {"recorded": True, "scheduler_status": crawler.scheduler.get_status()}


@router.get("/config")
def get_config(user_id: str = Depends(get_current_user)):
    """获取当前评分配置"""
    crawler = _get_crawler()
    return {
        "keywords": crawler.scorer.KEYWORD_WEIGHTS,
        "budget_tiers": [
            {"threshold": t, "score": s, "label": l}
            for t, s, l in crawler.scorer.BUDGET_TIERS
        ],
        "scheduler_intervals": [
            {"threshold": th, "seconds": iv, "mode": m, "label": lb}
            for th, iv, m, lb in crawler.scheduler.INTERVAL_TIERS
        ],
    }


@router.put("/config")
def update_config(req: ConfigUpdateRequest, user_id: str = Depends(get_current_user)):
    """热更新评分关键词配置"""
    crawler = _get_crawler()
    if req.keywords:
        crawler.scorer.KEYWORD_WEIGHTS.update(req.keywords)
    return {"updated": True, "keywords": crawler.scorer.KEYWORD_WEIGHTS}
