"""安全工具模块"""

import hmac
import re
import time
from collections import defaultdict
from functools import wraps
from typing import Callable, Dict, List, Tuple

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
    import secrets

    return secrets.token_hex(16)


def hash_password(password: str, salt: str) -> Tuple[str, str]:
    """密码哈希"""
    import hashlib

    if not salt:
        import secrets

        salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return pwd_hash.hex(), salt


def verify_password(password: str, pwd_hash: str, salt: str) -> bool:
    """验证密码"""
    computed_hash, _ = hash_password(password, salt)
    return hmac.compare_digest(computed_hash, pwd_hash)


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;",
}


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
