"""用户管理路由"""

import os
import secrets
import sys

from fastapi import APIRouter, Body, Header, HTTPException, Query

# 这是必要的，因为 app 模块在父目录中
sys_path = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)  # noqa: E402
sys.path.insert(0, sys_path)  # noqa: E402

from app.database import get_db  # noqa: E402
from app.utils.security import (  # noqa: E402
    check_lockout,
    clear_failed_login,
    hash_password,
    rate_limit,
    record_failed_login,
    sanitize_input,
    verify_password,
)
from app.utils.session import (  # noqa: E402
    create_session,
    delete_session,
    get_user_from_session,
)

router = APIRouter(prefix="/api/users", tags=["用户管理"])


@router.post("/register", summary="用户注册", description="创建新用户账户")
@rate_limit(max_requests=100, window=60)  # 100次/分钟
async def register(
    username: str = Body(...),
    password: str = Body(...),
    display_name: str = Body(""),
):
    """用户注册"""
    username_sanitized = sanitize_input(username, 32)
    if not username_sanitized:
        raise HTTPException(status_code=400, detail="用户名无效")

    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6个字符")

    db = get_db()
    existing = db.get_user_by_username(username_sanitized)
    if existing:
        raise HTTPException(status_code=409, detail="用户名已存在")

    pwd_hash, salt = hash_password(password)
    user_id = secrets.token_hex(16)

    db.create_user(
        {
            "user_id": user_id,
            "username": username_sanitized,
            "password_hash": pwd_hash,
            "password_salt": salt,
            "display_name": sanitize_input(display_name, 50),
            "role": "viewer",
        }
    )

    return {"user_id": user_id, "username": username_sanitized, "role": "viewer"}


@router.post("/login", summary="用户登录", description="验证用户名密码")
@rate_limit(max_requests=100, window=60)  # 100次/分钟，防止暴力破解同时允许正常测试
async def login(
    username: str = Body(...),
    password: str = Body(...),
):
    """用户登录"""
    username_sanitized = sanitize_input(username, 32)

    if check_lockout(username_sanitized):
        raise HTTPException(status_code=423, detail="账户已被锁定，请30分钟后再试")

    db = get_db()
    user = db.get_user_by_username(username_sanitized)

    if not user or not verify_password(password, user["password_hash"], user["password_salt"]):
        record_failed_login(username_sanitized)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    clear_failed_login(username_sanitized)
    db.update_user_last_login(user["user_id"])

    token = create_session(user["user_id"], user["role"])

    return {
        "token": token,
        "user": {"user_id": user["user_id"], "username": user["username"], "role": user["role"]},
    }


@router.post("/logout", summary="用户登出", description="清除当前session")
async def logout(x_session_token: str = Header(None, alias="X-Session-Token")):
    """用户登出"""
    if x_session_token:
        delete_session(x_session_token)
    return {"status": "ok"}


@router.get("/me", summary="获取当前用户")
async def get_me(x_session_token: str = Header(None, alias="X-Session-Token")):
    """获取当前用户信息"""
    if not x_session_token:
        raise HTTPException(status_code=401, detail="未登录")

    user = get_user_from_session(x_session_token)
    if not user:
        raise HTTPException(status_code=401, detail="无效的session")

    return user


@router.post("/change-password", summary="修改密码", description="修改当前用户的密码")
async def change_password(
    old_password: str = Body(...),
    new_password: str = Body(...),
    x_session_token: str = Header(None, alias="X-Session-Token"),
):
    """修改密码"""
    if not x_session_token:
        raise HTTPException(status_code=401, detail="未登录")

    user = get_user_from_session(x_session_token)
    if not user:
        raise HTTPException(status_code=401, detail="无效的session")

    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少6个字符")

    db = get_db()
    db_user = db.get_user_by_id(user["user_id"])

    if not verify_password(old_password, db_user["password_hash"], db_user["password_salt"]):
        raise HTTPException(status_code=401, detail="原密码错误")

    new_hash, new_salt = hash_password(new_password)
    db.update_user_password(user["user_id"], new_hash, new_salt)

    return {"status": "ok"}


@router.post("/admin/create", summary="创建用户", description="创建新用户（需管理员权限）")
async def admin_create_user(
    username: str = Body(...),
    password: str = Body(...),
    role: str = Body("viewer"),
    x_session_token: str = Header(None, alias="X-Session-Token"),
):
    """管理员创建用户"""
    if not x_session_token:
        raise HTTPException(status_code=401, detail="未登录")

    user = get_user_from_session(x_session_token)
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")

    username_sanitized = sanitize_input(username, 32)
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6个字符")

    db = get_db()
    existing = db.get_user_by_username(username_sanitized)
    if existing:
        raise HTTPException(status_code=409, detail="用户名已存在")

    pwd_hash, salt = hash_password(password)
    user_id = secrets.token_hex(16)

    db.create_user(
        {
            "user_id": user_id,
            "username": username_sanitized,
            "password_hash": pwd_hash,
            "password_salt": salt,
            "display_name": username_sanitized,
            "role": role if role in ("admin", "editor", "viewer") else "viewer",
        }
    )

    return {"user_id": user_id, "username": username_sanitized, "role": role}


@router.get("/admin/list", summary="用户列表", description="获取所有用户（需管理员权限）")
async def admin_list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    x_session_token: str = Header(None, alias="X-Session-Token"),
):
    """管理员获取用户列表"""
    if not x_session_token:
        raise HTTPException(status_code=401, detail="未登录")

    user = get_user_from_session(x_session_token)
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")

    db = get_db()
    users, total = db.list_users_paged(page, page_size)

    return {"users": users, "total": total, "page": page, "page_size": page_size}


@router.delete(
    "/admin/delete/{target_uid}", summary="删除用户", description="删除指定用户（需管理员权限）"
)
async def delete_user(
    target_uid: str,
    x_session_token: str = Header(None, alias="X-Session-Token"),
):
    """管理员删除用户"""
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
    """获取用户统计数据（total/active/admins/operators）"""
    if not x_session_token:
        raise HTTPException(status_code=401, detail="未登录")

    user = get_user_from_session(x_session_token)
    if not user:
        raise HTTPException(status_code=401, detail="无效的session")

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
    """管理员更新用户信息"""
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
    """管理员重置用户密码"""
    if not x_session_token:
        raise HTTPException(status_code=401, detail="未登录")

    user = get_user_from_session(x_session_token)
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")

    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6个字符")

    db = get_db()
    target = db.get_user_by_id(target_uid)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")

    new_hash, new_salt = hash_password(new_password)
    db.update_user_password(target_uid, new_hash, new_salt)

    return {"status": "ok"}
