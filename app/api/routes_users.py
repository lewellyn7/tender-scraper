"""用户管理路由 - 支持双模式切换"""
import os
import secrets
import sys
from app.security.audit import write_audit_log, EVENT_LOGIN_SUCCESS, EVENT_LOGIN_FAILURE, EVENT_LOGOUT, EVENT_PASSWORD_CHANGED
from fastapi import APIRouter, Body, Header, HTTPException, Query, Request
from app.config.settings import get_settings

# 这是必要的，因为 app 模块在父目录中
sys_path = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, sys_path)

from app.database import get_db
from app.utils.security import (
    check_lockout, clear_failed_login, hash_password, rate_limit,
    record_failed_login, sanitize_input, verify_password,
)
from app.utils.session import (
    create_session, delete_session, get_user_from_session,
)

router = APIRouter(prefix="/api/users", tags=["用户管理"])


@router.post("/register", summary="用户注册", description="创建新用户账户")
@rate_limit(max_requests=100, window=60)
async def register(
    username: str = Body(...),
    password: str = Body(...),
    display_name: str = Body(""),
):
    """用户注册 - 自用模式下禁用"""
    settings = get_settings()
    
    # 自用模式：禁用注册
    if settings.is_self_mode:
        raise HTTPException(status_code=403, detail="自用模式下禁用用户注册功能")
    
    username_sanitized = sanitize_input(username, 32)
    if not username_sanitized:
        raise HTTPException(status_code=400, detail="用户名无效")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 个字符")
    
    db = get_db()
    existing = db.get_user_by_username(username_sanitized)
    if existing:
        raise HTTPException(status_code=409, detail="用户名已存在")
    
    pwd_hash, salt = hash_password(password)
    user_id = secrets.token_hex(16)
    db.create_user({
        "user_id": user_id,
        "username": username_sanitized,
        "password_hash": pwd_hash,
        "password_salt": salt,
        "display_name": sanitize_input(display_name, 50),
        "role": "viewer",
    })
    return {"user_id": user_id, "username": username_sanitized, "role": "viewer"}


@router.post("/login", summary="用户登录", description="验证用户名密码")
@rate_limit(max_requests=100, window=60)
async def login(
    request: Request,
    username: str = Body(...),
    password: str = Body(...),
):
    """用户登录 - 自用模式自动返回 admin token"""
    settings = get_settings()
    
    # 自用模式：直接返回 admin token
    if settings.is_self_mode:
        token = create_session("admin", "admin")
        import secrets as sec
        csrf_token = sec.token_hex(16)
        from fastapi.responses import JSONResponse
        resp = JSONResponse({
            "token": token,
            "user": {"user_id": "admin", "username": "admin", "role": "admin"}
        })
        resp.set_cookie("session_token", value=token, httponly=True, samesite="lax", max_age=86400)
        resp.set_cookie("csrf_token", value=csrf_token, httponly=False, samesite="lax", max_age=86400)
        return resp
    
    # 团队模式：正常登录流程
    username_sanitized = sanitize_input(username, 32)
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", None)
    
    if check_lockout(username_sanitized):
        write_audit_log(EVENT_LOGIN_FAILURE, user_id=username_sanitized, ip_address=client_ip, user_agent=user_agent, result="lockout")
        raise HTTPException(status_code=423, detail="账户已被锁定，请 30 分钟后再试")
    
    db = get_db()
    user = db.get_user_by_username(username_sanitized)
    
    # 测试模式：跳过密码验证
    TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"
    if not TEST_MODE and (not user or not verify_password(password, user["password_hash"], user["password_salt"])):
        record_failed_login(username_sanitized)
        write_audit_log(EVENT_LOGIN_FAILURE, user_id=username_sanitized, ip_address=client_ip, user_agent=user_agent, result="invalid_password")
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    if not user:
        write_audit_log(EVENT_LOGIN_FAILURE, user_id=username_sanitized, ip_address=client_ip, user_agent=user_agent, result="user_not_found")
        raise HTTPException(status_code=401, detail="用户不存在")
    
    clear_failed_login(username_sanitized)
    db.update_user_last_login(user["user_id"])
    token = create_session(user["user_id"], user["role"])
    write_audit_log(EVENT_LOGIN_SUCCESS, user_id=user["user_id"], ip_address=client_ip, user_agent=user_agent, result="success", details={"username": user["username"], "role": user["role"]})
    
    import secrets as sec
    csrf_token = sec.token_hex(16)
    from fastapi.responses import JSONResponse
    resp = JSONResponse({
        "token": token,
        "user": {"user_id": user["user_id"], "username": user["username"], "role": user["role"]}
    })
    resp.set_cookie("session_token", value=token, httponly=True, samesite="lax", max_age=86400)
    resp.set_cookie("csrf_token", value=csrf_token, httponly=False, samesite="lax", max_age=86400)
    return resp


@router.post("/logout", summary="用户登出", description="清除当前 session")
async def logout(
    request: Request,
    x_session_token: str = Header(None, alias="X-Session-Token"),
):
    """用户登出"""
    user = None
    if x_session_token:
        user = get_user_from_session(x_session_token)
    delete_session(x_session_token)
    write_audit_log(
        EVENT_LOGOUT,
        user_id=user["user_id"] if user else None,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        result="success",
    )
    return {"status": "ok"}


@router.get("/me", summary="获取当前用户")
async def get_me(x_session_token: str = Header(None, alias="X-Session-Token")):
    """获取当前用户信息"""
    settings = get_settings()
    
    # 自用模式：返回 admin 用户
    if settings.is_self_mode:
        return {"user_id": "admin", "username": "admin", "role": "admin", "display_name": "系统管理员"}
    
    if not x_session_token:
        raise HTTPException(status_code=401, detail="未登录")
    user = get_user_from_session(x_session_token)
    if not user:
        raise HTTPException(status_code=401, detail="无效的 session")
    return user


@router.post("/change-password", summary="修改密码", description="修改当前用户的密码")
async def change_password(
    request: Request,
    old_password: str = Body(...),
    new_password: str = Body(...),
    x_session_token: str = Header(None, alias="X-Session-Token"),
):
    """修改密码 - 自用模式下禁用"""
    settings = get_settings()
    if settings.is_self_mode:
        raise HTTPException(status_code=403, detail="自用模式下禁用密码修改功能")
    
    if not x_session_token:
        raise HTTPException(status_code=401, detail="未登录")
    user = get_user_from_session(x_session_token)
    if not user:
        raise HTTPException(status_code=401, detail="无效的 session")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 个字符")
    
    db = get_db()
    db_user = db.get_user_by_id(user["user_id"])
    if not verify_password(old_password, db_user["password_hash"], db_user["password_salt"]):
        write_audit_log(EVENT_PASSWORD_CHANGED, user_id=user["user_id"], ip_address=request.client.host if request.client else None, user_agent=request.headers.get("user-agent"), result="failure", details={"reason": "invalid_old_password"})
        raise HTTPException(status_code=401, detail="原密码错误")
    
    new_hash, new_salt = hash_password(new_password)
    db.update_user_password(user["user_id"], new_hash, new_salt)
    write_audit_log(EVENT_PASSWORD_CHANGED, user_id=user["user_id"], ip_address=request.client.host if request.client else None, user_agent=request.headers.get("user-agent"), result="success")
    return {"status": "ok"}


@router.post("/admin/create", summary="创建用户", description="创建新用户（需管理员权限）")
async def admin_create_user(
    username: str = Body(...),
    password: str = Body(...),
    role: str = Body("viewer"),
    x_session_token: str = Header(None, alias="X-Session-Token"),
):
    """管理员创建用户 - 自用模式下禁用"""
    settings = get_settings()
    if settings.is_self_mode:
        raise HTTPException(status_code=403, detail="自用模式下禁用用户管理功能")
    
    if not x_session_token:
        raise HTTPException(status_code=401, detail="未登录")
    user = get_user_from_session(x_session_token)
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    
    username_sanitized = sanitize_input(username, 32)
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 个字符")
    
    db = get_db()
    existing = db.get_user_by_username(username_sanitized)
    if existing:
        raise HTTPException(status_code=409, detail="用户名已存在")
    
    pwd_hash, salt = hash_password(password)
    user_id = secrets.token_hex(16)
    db.create_user({
        "user_id": user_id,
        "username": username_sanitized,
        "password_hash": pwd_hash,
        "password_salt": salt,
        "display_name": username_sanitized,
        "role": role if role in ("admin", "editor", "viewer") else "viewer",
    })
    return {"user_id": user_id, "username": username_sanitized, "role": role}


@router.get("/admin/list", summary="用户列表", description="获取所有用户（需管理员权限）")
async def admin_list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    x_session_token: str = Header(None, alias="X-Session-Token"),
):
    """管理员获取用户列表 - 自用模式返回单个 admin 用户"""
    settings = get_settings()
    
    # 自用模式：返回单个 admin 用户
    if settings.is_self_mode:
        return {
            "users": [{"user_id": "admin", "username": "admin", "role": "admin", "display_name": "系统管理员", "enabled": 1}],
            "total": 1,
            "page": page,
            "page_size": page_size
        }
    
    if not x_session_token:
        raise HTTPException(status_code=401, detail="未登录")
    user = get_user_from_session(x_session_token)
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    
    db = get_db()
    users, total = db.list_users_paged(page, page_size)
    return {"users": users, "total": total, "page": page, "page_size": page_size}


@router.delete("/admin/delete/{target_uid}", summary="删除用户", description="删除指定用户（需管理员权限）")
async def delete_user(
    target_uid: str,
    x_session_token: str = Header(None, alias="X-Session-Token"),
):
    """管理员删除用户 - 自用模式下禁用"""
    settings = get_settings()
    if settings.is_self_mode:
        raise HTTPException(status_code=403, detail="自用模式下禁用用户管理功能")
    
    if not x_session_token:
        raise HTTPException(status_code=401, detail="未登录")
    user = get_user_from_session(x_session_token)
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    if target_uid == user["user_id"]:
        raise HTTPException(status_code=400, detail="不能删除自己")
    
    db = get_db()
    db.delete_user(target_uid)
    return {"status": "ok"}


@router.get("/stats", summary="用户统计", description="获取用户统计数据")
async def get_user_stats(
    x_session_token: str = Header(None, alias="X-Session-Token"),
):
    """获取用户统计数据 - 自用模式返回 admin 统计"""
    settings = get_settings()
    
    # 自用模式：返回 admin 统计
    if settings.is_self_mode:
        return {"total": 1, "active": 1, "admins": 1, "operators": 0}
    
    if not x_session_token:
        raise HTTPException(status_code=401, detail="未登录")
    user = get_user_from_session(x_session_token)
    if not user:
        raise HTTPException(status_code=401, detail="无效的 session")
    
    db = get_db()
    return db.get_user_stats()


@router.patch("/admin/update/{target_uid}", summary="更新用户", description="更新用户信息（需管理员权限）")
async def admin_update_user(
    target_uid: str,
    display_name: str = Body(None),
    role: str = Body(None),
    enabled: bool = Body(None),
    x_session_token: str = Header(None, alias="X-Session-Token"),
):
    """管理员更新用户信息 - 自用模式下禁用"""
    settings = get_settings()
    if settings.is_self_mode:
        raise HTTPException(status_code=403, detail="自用模式下禁用用户管理功能")
    
    if not x_session_token:
        raise HTTPException(status_code=401, detail="未登录")
    user = get_user_from_session(x_session_token)
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    
    updates = {}
    if display_name is not None:
        updates["display_name"] = sanitize_input(display_name, 50)
    if role is not None:
        if role not in ("admin", "editor", "operator", "viewer"):
            raise HTTPException(status_code=400, detail="无效的角色")
        updates["role"] = role
    if enabled is not None:
        updates["enabled"] = 1 if enabled else 0
    if not updates:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")
    
    db = get_db()
    db.update_user(target_uid, updates)
    return {"status": "ok", "updated": updates}


@router.post("/admin/reset-password/{target_uid}", summary="重置密码", description="重置用户密码（需管理员权限）")
async def admin_reset_password(
    target_uid: str,
    new_password: str = Body(...),
    x_session_token: str = Header(None, alias="X-Session-Token"),
):
    """管理员重置用户密码 - 自用模式下禁用"""
    settings = get_settings()
    if settings.is_self_mode:
        raise HTTPException(status_code=403, detail="自用模式下禁用用户管理功能")
    
    if not x_session_token:
        raise HTTPException(status_code=401, detail="未登录")
    user = get_user_from_session(x_session_token)
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 个字符")
    
    db = get_db()
    target = db.get_user_by_id(target_uid)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    new_hash, new_salt = hash_password(new_password)
    db.update_user_password(target_uid, new_hash, new_salt)
    return {"status": "ok"}
