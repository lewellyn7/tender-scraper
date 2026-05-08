"""收藏路由"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import get_current_user
from app.database import get_db
from app.security.audit import write_audit_log, EVENT_DATA_DELETE

router = APIRouter(prefix="/api/favorites", tags=["收藏"])


def _serialize(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def _serialize_row(row):
    return {k: _serialize(v) for k, v in row.items()}


# ─── GET /favorites ────────────────────────────────────────────────

@router.get("")
def get_favorites(
    request: Request,
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """获取收藏列表（支持分页 + 状态过滤）"""
    user = get_current_user(request)
    db = get_db()
    total = db.get_favorite_count(user_id=user["user_id"], status=status)
    favorites = db.get_favorites(user_id=user["user_id"], status=status, limit=limit, offset=offset)
    return JSONResponse({
        "favorites": [_serialize_row(f) for f in favorites],
        "total": total,
        "limit": limit,
        "offset": offset,
    })


# ─── GET /favorites/{project_url} ─────────────────────────────────

@router.get("/{project_url}")
def get_favorite(request: Request, project_url: str):
    """获取单条收藏"""
    user = get_current_user(request)
    db = get_db()
    fav = db.get_favorite(project_url=project_url, user_id=user["user_id"])
    if not fav:
        raise HTTPException(status_code=404, detail="收藏不存在")
    return JSONResponse({"favorite": _serialize_row(fav)})


# ─── POST /favorites ──────────────────────────────────────────────

@router.post("")
def add_favorite(request: Request, project: dict = Body(...)):
    """添加/更新收藏"""
    user = get_current_user(request)
    url = project.get("url", "")
    if not url:
        raise HTTPException(status_code=400, detail="缺少 url 字段")
    db = get_db()
    success = db.add_favorite_sync(project, user_id=user["user_id"])
    if success:
        return JSONResponse({"success": True, "message": "已添加到收藏"})
    return JSONResponse({"success": False, "error": "添加失败"}, status_code=500)


# ─── PATCH /favorites/{project_url}/status ───────────────────────

@router.patch("/{project_url}/status")
def update_favorite_status(
    request: Request,
    project_url: str,
    body: dict = Body(...),
):
    """更新收藏状态"""
    user = get_current_user(request)
    new_status = body.get("status", "")
    if not new_status:
        raise HTTPException(status_code=400, detail="缺少 status 字段")
    db = get_db()
    # 先查是否存在
    fav = db.get_favorite(project_url=project_url, user_id=user["user_id"])
    if not fav:
        raise HTTPException(status_code=404, detail="收藏不存在")
    success = db.update_favorite_status(project_url, new_status, user_id=user["user_id"])
    if success:
        return JSONResponse({"success": True})
    return JSONResponse({"success": False}, status_code=500)


# ─── DELETE /favorites/{project_url} ─────────────────────────────

@router.delete("/{project_url}")
def remove_favorite(request: Request, project_url: str):
    """删除收藏"""
    user = get_current_user(request)
    db = get_db()
    success = db.remove_favorite(project_url, user_id=user["user_id"])
    write_audit_log(
        EVENT_DATA_DELETE,
        user_id=user["user_id"],
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        resource=project_url,
        result="success" if success else "failure",
        details={"operation": "remove_favorite"},
    )
    if success:
        return JSONResponse({"success": True})
    return JSONResponse({"success": False}, status_code=500)


# ─── POST /favorites/batch ────────────────────────────────────────

@router.post("/batch")
def add_favorites_batch(request: Request, projects: list = Body(...)):
    """批量添加收藏"""
    user = get_current_user(request)
    db = get_db()
    count = db.add_favorites_batch(projects, user_id=user["user_id"])
    return JSONResponse({"success": True, "count": count})


# ─── GET /favorites/search ───────────────────────────────────────

@router.get("/search/query")
def search_favorites(
    request: Request,
    q: str = Query(..., min_length=1),
    tender_type: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
):
    """全文检索收藏"""
    user = get_current_user(request)
    db = get_db()
    results = db.search_favorites(
        query=q,
        user_id=user["user_id"],
        tender_type=tender_type,
        limit=limit,
    )
    return JSONResponse({"favorites": [_serialize_row(f) for f in results]})
