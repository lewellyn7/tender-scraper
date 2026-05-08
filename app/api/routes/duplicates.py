"""重复检测路由 — 多字段智能查重（分桶优化 O(n²) → O(n×k)）"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import get_current_user
from app.database import get_db
from app.utils.dedup import find_duplicate_groups, FIELD_WEIGHTS

router = APIRouter(prefix="/api/duplicates", tags=["重复检测"])


# ─── GET /duplicates ──────────────────────────────────────────────

@router.get("")
def find_duplicates(
    request: Request,
    threshold: float = Query(0.5, ge=0.1, le=1.0),
    save: bool = Query(False, description="是否将结果持久化到 duplicate_records 表"),
):
    """
    多字段智能查重（分桶预过滤 O(n²) → O(n×k)）。

    比对维度：标题(40%)、预算(20%)、项目类型(15%)、URL(15%)、发布日期(10%)
    每组结果包含：综合分数、各字段得分、匹配标记
    """
    user = get_current_user(request)
    uid = user["user_id"]

    db = get_db()
    conn = db._get_conn()

    rows = conn.execute(
        "SELECT * FROM favorites WHERE user_id=? ORDER BY updated_at DESC LIMIT 2000",
        (uid,),
    ).fetchall()
    projects = [dict(r) for r in rows]

    if len(projects) < 2:
        return JSONResponse({
            "duplicates": [],
            "count": 0,
            "total": 0,
            "threshold": threshold,
            "saved": False,
        })

    groups, pairs = find_duplicate_groups(projects, threshold=threshold)

    if save and pairs:
        try:
            saved = db.add_duplicates_batch(pairs, user_id=uid)
        except Exception:
            saved = 0
    else:
        saved = len(pairs) if save else 0

    flat_groups = []
    for g in groups:
        items = [g["canonical"]] + [d for d in g["duplicates"]]
        flat_groups.append(items)

    return JSONResponse({
        "duplicates": flat_groups,
        "count": len(groups),
        "total": sum(len(g) for g in flat_groups),
        "threshold": threshold,
        "saved": saved,
    })


# ─── GET /duplicates/computed ──────────────────────────────────────

@router.get("/computed")
def get_computed_duplicates(
    request: Request,
    canonical_url: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
):
    """获取已持久化的重复记录"""
    user = get_current_user(request)
    uid = user["user_id"]

    db = get_db()
    rows = db.get_duplicates(user_id=uid, canonical_url=canonical_url, limit=limit)

    # 按 canonical_url 分组
    by_canonical = {}
    for r in rows:
        cu = r.get("canonical_url", "")
        if cu not in by_canonical:
            by_canonical[cu] = []
        by_canonical[cu].append(r)

    groups = []
    for cu, dupes in by_canonical.items():
        groups.append({
            "canonical_url": cu,
            "canonical_title": dupes[0].get("duplicate_title", "") if dupes else "",
            "duplicates": [
                {
                    "url": d.get("duplicate_url", ""),
                    "title": d.get("duplicate_title", ""),
                    "similarity": d.get("similarity_score", 0),
                    "detected_at": d.get("detected_at", ""),
                }
                for d in dupes
            ],
        })

    return JSONResponse({
        "groups": groups,
        "count": len(groups),
        "total": sum(len(g["duplicates"]) for g in groups),
    })


# ─── GET /duplicates/stats ─────────────────────────────────────────

@router.get("/stats")
def get_duplicate_stats(request: Request):
    """获取查重统计"""
    user = get_current_user(request)
    uid = user["user_id"]

    db = get_db()
    total_pairs = db.get_computed_duplicates_count(user_id=uid)
    rows = db.get_duplicates(user_id=uid, limit=10000)
    unique_canonicals = len({r.get("canonical_url", "") for r in rows})

    return JSONResponse({
        "total_duplicate_pairs": total_pairs,
        "unique_canonical_urls": unique_canonicals,
        "field_weights": FIELD_WEIGHTS,
    })


# ─── DELETE /duplicates ────────────────────────────────────────────

@router.delete("/all")
def clear_duplicates(request: Request):
    """清空当前用户的重复记录"""
    user = get_current_user(request)
    uid = user["user_id"]

    db = get_db()
    success = db.clear_duplicates(user_id=uid)
    if success:
        return JSONResponse({"success": True, "message": "已清空重复记录"})
    return JSONResponse({"success": False, "error": "清空失败"}, status_code=500)
