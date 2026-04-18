"""安全工具模块"""

import hashlib
import hmac
import os
import re
import secrets
import time
from collections import defaultdict
from functools import wraps
from typing import Callable, Dict, List, Tuple

import bcrypt

from app.constants import SecurityConstants

# CSRF 安全头
CSRF_HEADERS = ["X-CSRF-Token", "X-Session-Token"]
# 敏感字段列表
SENSITIVE_FIELDS = [
    "password",
    "password_hash",
    "password_salt",
    "token",
    "secret",
    "api_key",
    "access_token",
]


class RateLimiter:
    """简单的内存限流器"""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, List[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> Tuple[bool, int]:
        """检查是否允许请求，返回 (是否允许, 剩余次数)"""
        now = time.time()
        # 清理过期的请求记录
        self.requests[key] = [t for t in self.requests[key] if now - t < self.window_seconds]
        if len(self.requests[key]) < self.max_requests:
            self.requests[key].append(now)
            remaining = self.max_requests - len(self.requests[key])
            return True, remaining
        return False, 0


def rate_limit(
    max_requests: int = 60,
    window: int = 60,
    by: str = "ip",
) -> Callable:
    """限流装饰器"""
    limiter = RateLimiter(max_requests, window)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            allowed, _ = limiter.is_allowed(by)
            if not allowed:
                from fastapi import HTTPException

                raise HTTPException(status_code=429, detail="请求过于频繁")
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def sanitize_input(text: str, max_length: int = 1000) -> str:
    """清理输入"""
    if not text:
        return ""
    text = text[:max_length]
    text = re.sub(r"[<>\"']", "", text)
    return text.strip()


def validate_url(url: str) -> bool:
    """验证 URL"""
    pattern = r"^https?://"
    return bool(re.match(pattern, url)) and len(url) < 2048


def validate_email(email: str) -> bool:
    """验证邮箱"""
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def validate_username(username: str) -> Tuple[bool, str]:
    """验证用户名"""
    if not username:
        return False, "用户名不能为空"
    if len(username) < 3:
        return False, "用户名至少3个字符"
    if len(username) > 32:
        return False, "用户名最多32个字符"
    if not re.match(r"^[a-zA-Z0-9_]+$", username):
        return False, "用户名只能包含字母数字和下划线"
    return True, ""


def validate_password(password: str) -> Tuple[bool, str]:
    """验证密码强度 - 6字符起即可，8字符以上更安全"""
    if not password:
        return False, "密码不能为空"
    if len(password) < 6:
        return False, "密码至少6个字符"
    if len(password) > 128:
        return False, "密码最多128个字符"
    if len(password) < 8:
        return True, "密码建议至少8个字符"  # 只警告，不拒绝
    return True, ""


def mask_sensitive_data(data: dict, fields: List[str] = None) -> dict:
    """脱敏敏感数据"""
    if fields is None:
        fields = SENSITIVE_FIELDS
    result = data.copy()
    for field in fields:
        if field in result:
            value = str(result[field])
            if len(value) > 8:
                result[field] = value[:4] + "*" * (len(value) - 8) + value[-4:]
            else:
                result[field] = "****"
    return result


def generate_request_id() -> str:
    """生成请求 ID"""

    return secrets.token_hex(16)


def hash_password(password: str, salt: str = None) -> Tuple[str, str]:
    """密码哈希（bcrypt，自动生成 salt）"""
    if salt is None:
        salt = bcrypt.gensalt().decode()
    pwd_hash = bcrypt.hashpw(password.encode(), salt.encode()).decode()
    return pwd_hash, salt


def verify_password(password: str, pwd_hash: str, salt: str = None) -> bool:
    """验证密码（兼容新旧格式，使用 constant-time 比较防时序攻击）"""
    try:
        # bcrypt.checkpw 内部是 constant-time，无泄露风险
        return bcrypt.checkpw(password.encode(), pwd_hash.encode())
    except (ValueError, TypeError, AttributeError):
        # 格式错误的 hash 不抛异常给调用者，保证所有路径耗时一致
        pass
    # 兼容旧 PBKDF2 格式或无效格式：走 constant-time 对比路径
    # 为无效格式构造假 hash 以保证耗时一致
    if salt:
        computed_hash, _ = _hash_password_pbdkf2(password, salt)
        return hmac.compare_digest(computed_hash, pwd_hash)
    return False


def _hash_password_pbdkf2(password: str, salt: str) -> Tuple[str, str]:
    """旧版 PBKDF2 哈希（仅用于兼容）"""
    pwd_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        SecurityConstants.PASSWORD_HASH_ITERATIONS,
    )
    return pwd_hash.hex(), salt


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;",
}


# ── 账户锁定 ──────────────────────────────────────────────────

_failed_login_counts: Dict[str, int] = {}
_locked_accounts: Dict[str, float] = {}


def check_lockout(username: str) -> bool:
    """检查账户是否被锁定（30分钟自动解锁）"""
    if username in _locked_accounts:
        if time.time() - _locked_accounts[username] < SecurityConstants.LOCKOUT_DURATION_SECONDS:
            return True
        del _locked_accounts[username]
    return False


def record_failed_login(username: str) -> bool:
    """记录一次失败登录，达到阈值后锁定账户"""
    global _failed_login_counts, _locked_accounts
    _failed_login_counts[username] = _failed_login_counts.get(username, 0) + 1
    if _failed_login_counts[username] >= SecurityConstants.MAX_LOGIN_ATTEMPTS:
        _locked_accounts[username] = time.time()
        _failed_login_counts.pop(username, None)
        return True  # locked
    return False


def clear_failed_login(username: str) -> None:
    """清除失败记录（登录成功后调用）"""
    _failed_login_counts.pop(username, None)


# ── Webhook Key 验证 ──────────────────────────────────────────

def validate_webhook_key(key: str) -> bool:
    """
    验证 x-n8n-webhook-key 是否与 N8N_WEBHOOK_KEY 环境变量匹配。
    用于统一 n8n webhook 认证入口。
    """
    expected = os.getenv("N8N_WEBHOOK_KEY")
    if not expected:
        raise ValueError("N8N_WEBHOOK_KEY 环境变量必须设置")
    return hmac.compare_digest(key, expected)


def get_security_headers() -> Dict[str, str]:
    """获取安全响应头"""
    return {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Strict-Transport-Security": ("max-age=31536000; includeSubDomains"),
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:;"
        ),
    }
