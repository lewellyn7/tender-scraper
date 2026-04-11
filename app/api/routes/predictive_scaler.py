"""
预测性扩容 API

GET  /api/scaler/status           - 当前状态 + 分析报告
GET  /api/scaler/predict           - 未来N小时预测
POST /api/scaler/record            - 记录采集快照
GET  /api/scaler/decision          - 获取当前扩容决策
GET  /api/scaler/config            - 获取扩容策略配置
PUT  /api/scaler/config            - 更新扩容策略配置
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, Optional

from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/scaler", tags=["predictive-scaler"])

# ── 全局单例 ──────────────────────────────────────────────────

_scaler: Optional[Any] = None


def _get_scaler():
    global _scaler
    if _scaler is None:
        from app.core.predictive_scaler import (
            ResourcePredictor,
            ScalingPolicy,
            TrendAnalyzer,
        )
        analyzer = TrendAnalyzer()
        policy = ScalingPolicy()
        _scaler = ResourcePredictor(trend_analyzer=analyzer)
        _scaler.policy = policy  # 挂载策略
    return _scaler


# ── Models ───────────────────────────────────────────────────


class RecordSnapshotRequest(BaseModel):
    tenders_found: int
    tenders_matched: int
    duration_ms: int
    success: bool
    error: Optional[str] = ""


class ConfigUpdateRequest(BaseModel):
    scale_up_threshold: Optional[int] = None
    scale_down_threshold: Optional[int] = None
    min_workers: Optional[int] = None
    max_workers: Optional[int] = None


# ── Routes ───────────────────────────────────────────────────


@router.get("/status")
def get_status(user_id: str = Depends(get_current_user)):
    """获取分析报告"""
    scaler = _get_scaler()
    return scaler.analyzer.analyze()


@router.get("/predict")
def predict(
    hours: int = 4,
    user_id: str = Depends(get_current_user),
):
    """预测未来N小时资源需求"""
    scaler = _get_scaler()
    result = scaler.predict_next_hours(hours=min(hours, 24))
    return result


@router.post("/record")
def record_snapshot(
    req: RecordSnapshotRequest,
    user_id: str = Depends(get_current_user),
):
    """记录采集快照"""
    scaler = _get_scaler()
    scaler.analyzer.record_run(
        tenders_found=req.tenders_found,
        tenders_matched=req.tenders_matched,
        duration_ms=req.duration_ms,
        success=req.success,
        error=req.error or "",
    )
    return {"recorded": True, "samples": len(scaler.analyzer.history)}


@router.get("/decision")
def get_decision(user_id: str = Depends(get_current_user)):
    """获取当前扩容决策"""
    scaler = _get_scaler()
    analysis = scaler.analyzer.analyze()
    decision = scaler.policy.evaluate(analysis, current_workers=2)
    return {
        "action": decision.action,
        "reason": decision.reason,
        "recommended_workers": decision.recommended_workers,
        "confidence": decision.confidence,
        "analysis_summary": {
            "trend": analysis.get("trend"),
            "success_rate": analysis.get("success_rate"),
            "avg_tenders_found": analysis.get("avg_tenders_found"),
            "is_anomaly": analysis.get("is_anomaly"),
        },
    }


@router.get("/config")
def get_config(user_id: str = Depends(get_current_user)):
    """获取扩容策略配置"""
    scaler = _get_scaler()
    p = scaler.policy
    return {
        "scale_up_threshold": p.scale_up_threshold,
        "scale_down_threshold": p.scale_down_threshold,
        "min_workers": p.min_workers,
        "max_workers": p.max_workers,
    }


@router.put("/config")
def update_config(
    req: ConfigUpdateRequest,
    user_id: str = Depends(get_current_user),
):
    """更新扩容策略配置（热更新）"""
    scaler = _get_scaler()
    p = scaler.policy
    if req.scale_up_threshold is not None:
        p.scale_up_threshold = req.scale_up_threshold
    if req.scale_down_threshold is not None:
        p.scale_down_threshold = req.scale_down_threshold
    if req.min_workers is not None:
        p.min_workers = max(1, req.min_workers)
    if req.max_workers is not None:
        p.max_workers = max(p.min_workers, req.max_workers)

    return {"updated": True, "config": get_config.__wrapped__(user_id="internal")}
