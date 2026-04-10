"""日志路由"""

from fastapi import APIRouter, Query, Depends
from fastapi.responses import JSONResponse

from app.database import get_db
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/logs", tags=["日志"])


@router.get("")
def get_logs(level: str = Query(""), limit: int = Query(200, ge=1, le=500), user_id: str = Depends(get_current_user)):
    return JSONResponse({"logs": get_db().get_logs(level if level else None, limit)})


@router.delete("")
def clear_logs(before_days: int = Query(7, ge=1), user_id: str = Depends(get_current_user)):
    get_db().clear_logs(before_days)
    return {"success": True}
