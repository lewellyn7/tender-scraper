"""Session 管理工具 - Redis 持久化"""

import secrets
import json
import time
from typing import Dict, Optional

from loguru import logger

from app.constants import SecurityConstants, TimeConstants

# Redis client (lazy init)
_redis = None

def _get_redis():
    """Get Redis client with automatic retry when previously failed"""
    global _redis
    if _redis is not None:
        return _redis
    import redis, os
    redis_url = os.getenv("REDIS_URL", "redis://:@redis:6379/0")
    try:
        _redis = redis.from_url(redis_url, decode_responses=True, socket_timeout=2)
        _redis.ping()
        logger.info("Session store: Redis connected")
    except Exception as e:
        logger.warning(f"Redis unavailable for sessions ({e}), falling back to in-memory")
        _redis = None
    return _redis


# 全局 in-memory sessions 缓存（重启后需从 Redis 恢复）
_sessions: Dict[str, dict] = {}
_session_cleanup_interval = 3600
_last_cleanup = time.time()

# Redis key prefix
_SESS_KEY = "sess:"


def _cleanup_expired_sessions() -> int:
    """清理过期的 sessions（仅内存缓存）"""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < _session_cleanup_interval:
        return 0
    _last_cleanup = now
    expired = [t for t, s in _sessions.items() if s["expires"] < now]
    for t in expired:
        del _sessions[t]
    if expired:
        logger.info(f"Cleaned up {len(expired)} expired sessions from cache")
    return len(expired)


def _redis_set(token: str, data: dict, ttl: int) -> bool:
    """Persist session to Redis"""
    r = _get_redis()
    if r is None:
        return False
    try:
        r.setex(f"{_SESS_KEY}{token}", ttl, json.dumps(data))
        return True
    except Exception as e:
        logger.warning(f"Redis session write failed: {e}")
        return False


def _redis_get(token: str) -> Optional[dict]:
    """Read session from Redis"""
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = r.get(f"{_SESS_KEY}{token}")
        if raw:
            return json.loads(raw)
        return None
    except Exception as e:
        logger.warning(f"Redis session read failed: {e}")
        return None


def _redis_delete(token: str) -> bool:
    """Delete session from Redis"""
    r = _get_redis()
    if r is None:
        return False
    try:
        r.delete(f"{_SESS_KEY}{token}")
        return True
    except Exception as e:
        logger.warning(f"Redis session delete failed: {e}")
        return False


def _redis_find_by_user(user_id: str) -> list:
    """Find all sessions for a user in Redis"""
    r = _get_redis()
    if r is None:
        return []
    try:
        keys = r.keys(f"{_SESS_KEY}*")
        user_tokens = []
        for key in keys:
            raw = r.get(key)
            if raw:
                data = json.loads(raw)
                if data.get("user_id") == user_id:
                    user_tokens.append(key[len(_SESS_KEY):])
        return user_tokens
    except Exception as e:
        logger.warning(f"Redis session search failed: {e}")
        return []


def create_session(user_id: str, role: str = "viewer", regenerate: bool = True) -> str:
    """创建新 session（防止 session fixation 攻击）"""
    _cleanup_expired_sessions()
    ttl = TimeConstants.SESSION_EXPIRY_SECONDS

    if regenerate:
        # 清除该用户的所有旧 session（防止 session fixation）
        tokens_to_delete = [t for t, s in _sessions.items() if s["user_id"] == user_id]
        tokens_to_delete += _redis_find_by_user(user_id)
        for t in set(tokens_to_delete):
            if t in _sessions:
                del _sessions[t]
            _redis_delete(t)
    else:
        user_tokens = [t for t, s in _sessions.items() if s["user_id"] == user_id]
        if len(user_tokens) >= SecurityConstants.MAX_DEVICES_PER_USER:
            raise ValueError(f"登录设备数已达上限 ({SecurityConstants.MAX_DEVICES_PER_USER})")

    token = secrets.token_urlsafe(SecurityConstants.SESSION_TOKEN_LENGTH)
    now = time.time()
    data = {
        "user_id": user_id,
        "role": role,
        "expires": now + ttl,
        "created_at": now,
    }

    # Memory cache
    _sessions[token] = data
    # Redis persistence
    _redis_set(token, data, ttl)

    return token


def get_session(token: str) -> Optional[dict]:
    """获取 session"""
    if not token:
        return None

    # Check memory cache first
    s = _sessions.get(token)
    if s and s["expires"] > time.time():
        return s

    # Fall back to Redis
    s = _redis_get(token)
    if s:
        # Restore to memory cache
        _sessions[token] = s
        return s

    # Expired or not found
    if token in _sessions:
        del _sessions[token]
    return None


def delete_session(token: str) -> bool:
    """删除 session"""
    if token in _sessions:
        del _sessions[token]
    _redis_delete(token)
    return True


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
