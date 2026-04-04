"""Session 管理工具"""

import secrets
import time
from typing import Dict, Optional

from loguru import logger

from app.constants import SecurityConstants, TimeConstants

# 全局 sessions 存储
_sessions: Dict[str, dict] = {}
_session_cleanup_interval = 3600  # 每小时清理一次
_last_cleanup = time.time()


def _cleanup_expired_sessions() -> int:
    """清理过期的 sessions，返回清理数量"""
    global _last_cleanup
    now = time.time()

    # 节流：避免频繁清理
    if now - _last_cleanup < _session_cleanup_interval:
        return 0

    _last_cleanup = now
    expired_tokens = [token for token, s in _sessions.items() if s["expires"] < now]

    for token in expired_tokens:
        del _sessions[token]

    if expired_tokens:
        logger.info(f"Cleaned up {len(expired_tokens)} expired sessions")

    return len(expired_tokens)


def create_session(user_id: str, role: str = "viewer", regenerate: bool = True) -> str:
    """创建新 session（防止 session fixation 攻击）"""
    # 定期清理过期 session
    _cleanup_expired_sessions()

    if regenerate:
        # 清除该用户的所有旧 session（防止 session fixation）
        tokens_to_delete = [t for t, s in _sessions.items() if s["user_id"] == user_id]
        for t in tokens_to_delete:
            del _sessions[t]
    else:
        # 检查并发登录数
        user_tokens = [t for t, s in _sessions.items() if s["user_id"] == user_id]
        if len(user_tokens) >= SecurityConstants.MAX_DEVICES_PER_USER:
            raise ValueError(f"登录设备数已达上限 ({SecurityConstants.MAX_DEVICES_PER_USER})")

    token = secrets.token_urlsafe(SecurityConstants.SESSION_TOKEN_LENGTH)
    _sessions[token] = {
        "user_id": user_id,
        "role": role,
        "expires": time.time() + TimeConstants.SESSION_EXPIRY_SECONDS,
        "created_at": time.time(),
    }
    return token


def get_session(token: str) -> Optional[dict]:
    """获取 session"""
    if not token:
        return None
    s = _sessions.get(token)
    if s and s["expires"] > time.time():
        return s
    if token in _sessions:
        del _sessions[token]
    return None


def delete_session(token: str) -> bool:
    """删除 session"""
    if token in _sessions:
        del _sessions[token]
        return True
    return False


def get_user_from_session(token: str) -> Optional[Dict]:
    """从 session 获取用户信息"""
    s = get_session(token)
    if not s:
        return None

    try:
        from app.database import get_db

        db = get_db()
        user = db.get_user_by_id(s["user_id"])
        if not user:
            return None

        return {
            "user_id": user["user_id"],
            "username": user["username"],
            "display_name": user.get("display_name", user["username"]),
            "role": user.get("role", "viewer"),
            "enabled": user.get("enabled", True),
        }
    except Exception as e:
        logger.warning(f"Failed to get user from session: {e}")
        return None


def cleanup_all_sessions() -> int:
    """清理所有过期的 sessions（可外部调用）"""
    return _cleanup_expired_sessions()


def get_session_stats() -> Dict:
    """获取 session 统计信息"""
    now = time.time()
    total = len(_sessions)
    expired = sum(1 for s in _sessions.values() if s["expires"] < now)
    return {
        "total": total,
        "expired": expired,
        "active": total - expired,
    }
