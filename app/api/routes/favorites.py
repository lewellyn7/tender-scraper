"""收藏路由"""

from datetime import datetime
from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import JSONResponse

from app.database import get_db
from app.utils.session import get_user_from_session

router = APIRouter(prefix="/api/favorites", tags=["收藏"])


def _serialize(obj):
    """将 datetime 对象转换为 ISO 字符串"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def _serialize_row(row):
    """序列化字典中的 datetime 字段"""
    return {k: _serialize(v) for k, v in row.items()}


def get_current_user_id(request) -> str:
    """获取当前用户ID"""
    token = request.cookies.get("session_token") or request.headers.get("X-Session-Token")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user = get_user_from_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="无效的session")
    return user["user_id"]


@router.get("")
def get_favorites(status: str = None, limit: int = 500):
    """获取收藏列表"""
    db = get_db()
    favorites = db.get_favorites(status=status, limit=limit)
    serialized = [_serialize_row(f) for f in favorites]
    return JSONResponse({"favorites": serialized})


@router.post("")
def add_favorite(project: dict = Body(...)):
    """添加收藏"""
    db = get_db()
    success = db.add_favorite_sync(project)
    if success:
        return JSONResponse({"success": True, "message": "已添加到收藏"})
    return JSONResponse({"success": False, "error": "添加失败"}, status_code=500)


@router.patch("/status")
def update_favorite_status(project_url: str = Query(...), status: dict = Body(...)):
    """更新收藏状态（query参数避免URL编码冲突）"""
    db = get_db()
    success = db.update_favorite_status(project_url, status.get("status") if isinstance(status, dict) else status)
    if success:
        return JSONResponse({"success": True})
    return JSONResponse({"success": False}, status_code=500)


@router.delete("")
def remove_favorite(project_url: str = Query(...)):
    """移除收藏（query参数避免URL编码冲突）"""
    db = get_db()
    success = db.remove_favorite(project_url)
    if success:
        return JSONResponse({"success": True})
    return JSONResponse({"success": False}, status_code=500)


@router.post("/batch")
def add_favorites_batch(projects: list = Body(...)):
    """批量添加收藏"""
    db = get_db()
    count = db.add_favorites_batch(projects)
    return JSONResponse({"success": True, "count": count})
