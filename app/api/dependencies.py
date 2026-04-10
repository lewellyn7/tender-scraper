"""FastAPI 认证依赖"""
from fastapi import HTTPException, Request, Depends


def get_current_user(request: Request) -> str:
    """FastAPI 依赖：验证当前用户，返回 user_id"""
    from app.utils.session import get_user_from_session
    
    token = request.cookies.get("session_token") or request.headers.get("X-Session-Token")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    
    user = get_user_from_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="无效的session")
    
    return user["user_id"]


def get_optional_user(request: Request) -> str | None:
    """FastAPI 依赖：可选用户，未登录返回 None"""
    from app.utils.session import get_user_from_session
    
    token = request.cookies.get("session_token") or request.headers.get("X-Session-Token")
    if not token:
        return None
    
    user = get_user_from_session(token)
    return user["user_id"] if user else None
