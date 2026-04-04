"""用户管理路由"""

import hashlib
import hmac
import os
import secrets
import sys
import time
from typing import Dict

from fastapi import APIRouter, Body, Header, HTTPException, Query

# 这是必要的，因为 app 模块在父目录中
sys_path = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)  # noqa: E402
sys.path.insert(0, sys_path)  # noqa: E402

from app.constants import SecurityConstants  # noqa: E402
from app.database import get_db  # noqa: E402
from app.utils.security import rate_limit, sanitize_input  # noqa: E402
from app.utils.session import (  # noqa: E402
    create_session,
    delete_session,
    get_user_from_session,
)

_failed_login_counts: Dict[str, int] = {}
_locked_accounts: Dict[str, float] = {}

router = APIRouter(prefix="/api/users", tags=["用户管理"])


def _hash_password(password: str, salt: str = None) -> tuple:
    """密码哈希"""
    if not salt:
        salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        SecurityConstants.PASSWORD_HASH_ITERATIONS,
    )
    return pwd_hash.hex(), salt


def _verify_password(password: str, pwd_hash: str, salt: str) -> bool:
    """验证密码"""
    computed_hash, _ = _hash_password(password, salt)
    return hmac.compare_digest(computed_hash, pwd_hash)


def _check_lockout(username: str) -> bool:
    """检查账户是否被锁定"""
    if username in _locked_accounts:
        if time.time() - _locked_accounts[username] < SecurityConstants.LOCKOUT_DURATION_SECONDS:
            return True
        del _locked_accounts[username]
    return False


@router.post("/register", summary="用户注册", description="创建新用户账户")
@rate_limit(max_requests=5, window=60)
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

    pwd_hash, salt = _hash_password(password)
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
@rate_limit(max_requests=10, window=60)
async def login(
    username: str = Body(...),
    password: str = Body(...),
):
    """用户登录"""
    username_sanitized = sanitize_input(username, 32)

    if _check_lockout(username_sanitized):
        raise HTTPException(status_code=423, detail="账户已被锁定，请30分钟后再试")

    db = get_db()
    user = db.get_user_by_username(username_sanitized)

    if not user or not _verify_password(password, user["password_hash"], user["password_salt"]):
        _failed_login_counts[username_sanitized] = (
            _failed_login_counts.get(username_sanitized, 0) + 1
        )
        if _failed_login_counts[username_sanitized] >= SecurityConstants.MAX_LOGIN_ATTEMPTS:
            _locked_accounts[username_sanitized] = time.time()
            del _failed_login_counts[username_sanitized]
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    _failed_login_counts.pop(username_sanitized, None)
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

    if not _verify_password(old_password, db_user["password_hash"], db_user["password_salt"]):
        raise HTTPException(status_code=401, detail="原密码错误")

    new_hash, new_salt = _hash_password(new_password)
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

    pwd_hash, salt = _hash_password(password)
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
