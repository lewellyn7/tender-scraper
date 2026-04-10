"""日志脱敏工具 - 移除敏感信息"""
import re
from typing import Any


SENSITIVE_PATTERNS = [
    # API keys, tokens
    (re.compile(r'(api[_-]?key["\']?\s*[:=]\s*["\']?)([a-zA-Z0-9_\-]{20,})'), r'\1[REDACTED]'),
    (re.compile(r'(token["\']?\s*[:=]\s*["\']?)([a-zA-Z0-9_\-]{20,})'), r'\1[REDACTED]'),
    (re.compile(r'(password["\']?\s*[:=]\s*["\']?)([^"\'\s,}]+)'), r'\1[REDACTED]'),
    (re.compile(r'(bearer\s+)([a-zA-Z0-9_\-\.]+)', re.IGNORECASE), r'\1[REDACTED]'),
    # RAGFlow API key
    (re.compile(r'(ragflow[-_][a-zA-Z0-9]{30,})'), r'[REDACTED_RAGFLOW_KEY]'),
    # Database URLs
    (re.compile(r'(postgresql://[^:]+:)([^@]+)(@)'), r'\1[REDACTED]\3'),
    (re.compile(r'(mysql://[^:]+:)([^@]+)(@)'), r'\1[REDACTED]\3'),
    # Redis URLs with password
    (re.compile(r'(redis://:?)([^@]+)(@)'), r'\1[REDACTED]\3'),
]


def sanitize_value(value: str) -> str:
    """对单个字符串值进行脱敏"""
    result = str(value)
    for pattern, replacement in SENSITIVE_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def sanitize_dict(data: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    """递归脱敏字典中的敏感字段"""
    if depth > 5:
        return {"[MAX_DEPTH]": "..."}
    
    result = {}
    for key, value in data.items():
        key_lower = key.lower()
        
        # 检查键名是否包含敏感关键词
        is_sensitive_key = any(
            kw in key_lower for kw in ['password', 'token', 'secret', 'key', 'api', 'auth', 'credential']
        )
        
        if is_sensitive_key:
            result[key] = "[REDACTED]"
        elif isinstance(value, str):
            result[key] = sanitize_value(value)
        elif isinstance(value, dict):
            result[key] = sanitize_dict(value, depth + 1)
        elif isinstance(value, (list, tuple)):
            result[key] = [
                sanitize_dict(item, depth + 1) if isinstance(item, dict) else sanitize_value(str(item)) if isinstance(item, str) else item
                for item in value
            ]
        else:
            result[key] = value
    
    return result


def sanitize_error_message(error: str, context: str = "") -> str:
    """对错误消息进行脱敏"""
    if not error:
        return error
    
    result = sanitize_value(error)
    
    # 移除可能的 URL 中的敏感参数
    result = re.sub(r'(\?[^"\']*)?(\&?[a-zA-Z_]*(?:key|token|password|secret)[^"\']*)=([^"\']*)', r'\1\2=[REDACTED]', result, flags=re.IGNORECASE)
    
    return result


def safe_log(message: str, **kwargs) -> str:
    """安全的日志格式，自动脱敏"""
    sanitized_msg = sanitize_error_message(message)
    
    if kwargs:
        sanitized_kwargs = {k: sanitize_value(str(v)) for k, v in kwargs.items()}
        return f"{sanitized_msg} | kwargs={sanitized_kwargs}"
    
    return sanitized_msg
