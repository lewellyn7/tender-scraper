"""质量评估路由"""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.services.quality_evaluation import QualityEvaluationService

router = APIRouter(prefix="/api/quality", tags=["质量评估"])

# 全局评估器单例
_evaluator = QualityEvaluationService()


@router.get("/evaluate")
async def evaluate(
    title: str = Query(..., description="标题"),
    content: str = Query("", description="正文内容"),
    budget: str = Query("", description="预算金额"),
    deadline: str = Query("", description="截止时间"),
    contact: str = Query("", description="联系方式"),
    attachments: str = Query("", description="附件数量（逗号分隔）"),
    publish_date: str = Query("", description="发布时间"),
):
    """评估单条招标记录的质量"""
    tender = {
        "title": title,
        "content_preview": content,
        "budget": budget,
        "submission_deadline": deadline,
        "contact_info": contact,
        "attachments": [a.strip() for a in attachments.split(",") if a.strip()] if attachments else [],
        "publish_date": publish_date,
    }

    score = _evaluator.evaluate(tender)

    return JSONResponse(content={
        "code": 0,
        "data": {
            "total": score.total,
            "completeness": score.completeness,
            "freshness": score.freshness,
            "accuracy": score.accuracy,
            "richness": score.richness,
            "issues": score.issues,
            "grade": _grade(score.total),
        },
    })


@router.get("/stats")
async def quality_stats():
    """获取质量统计（全局平均分 + 分布）"""
    avg = _evaluator.get_avg_scores()
    dist = _evaluator.get_quality_distribution()
    history_count = len(_evaluator.get_history())

    return JSONResponse(content={
        "code": 0,
        "data": {
            "avg": avg,
            "distribution": dist,
            "total_evaluated": history_count,
        },
    })


def _grade(score: float) -> str:
    """分数转等级"""
    if score >= 90:
        return "A+"
    elif score >= 80:
        return "A"
    elif score >= 70:
        return "B"
    elif score >= 60:
        return "C"
    elif score >= 50:
        return "D"
    else:
        return "F"
