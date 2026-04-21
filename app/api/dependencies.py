"""FastAPI 认证依赖"""
from fastapi import HTTPException, Request, Depends
from app.config.settings import get_settings


def get_current_user(request: Request) -> dict:
    """FastAPI 依赖：验证当前用户，返回用户信息
    
    自用模式：返回虚拟 admin 用户
    团队模式：正常验证 Session Token
    """
    from app.utils.session import get_user_from_session
    
    settings = get_settings()
    
    # 自用模式：返回虚拟 admin 用户
    if settings.is_self_mode:
        return {
            "user_id": "admin",
            "username": "admin",
            "role": "admin",
            "display_name": "系统管理员"
        }
    
    # 团队模式：正常验证 Session Token
    token = request.cookies.get("session_token") or request.headers.get("X-Session-Token")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    
    user = get_user_from_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="无效的 session")
    
    return user


def get_optional_user(request: Request) -> dict | None:
    """FastAPI 依赖：可选用户，未登录返回 None
    
    自用模式：返回虚拟 admin 用户
    团队模式：尝试获取用户
    """
    from app.utils.session import get_user_from_session
    
    settings = get_settings()
    
    # 自用模式：返回虚拟 admin 用户
    if settings.is_self_mode:
        return {
            "user_id": "admin",
            "username": "admin",
            "role": "admin",
            "display_name": "系统管理员"
        }
    
    # 团队模式：尝试获取用户
    token = request.cookies.get("session_token") or request.headers.get("X-Session-Token")
    if not token:
        return None
    
    user = get_user_from_session(token)
    return user if user else None
