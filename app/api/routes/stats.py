"""统计路由"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.database import get_db
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/stats", tags=["统计"])


@router.get("")
def get_stats(user_id: str = Depends(get_current_user)):
    """获取系统统计"""
    db = get_db()
    return JSONResponse(db.get_stats())


@router.get("/user")
def get_user_stats(user_id: str = Depends(get_current_user)):
    """获取用户统计"""
    db = get_db()
    return JSONResponse(db.get_user_stats())
