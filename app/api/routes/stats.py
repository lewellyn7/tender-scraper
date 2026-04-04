"""统计路由"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.database import get_db

router = APIRouter(prefix="/api/stats", tags=["统计"])


@router.get("")
def get_stats():
    """获取系统统计"""
    db = get_db()
    return JSONResponse(db.get_stats())


@router.get("/user")
def get_user_stats():
    """获取用户统计"""
    db = get_db()
    return JSONResponse(db.get_user_stats())
