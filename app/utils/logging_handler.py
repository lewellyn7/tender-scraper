"""安全日志处理器"""

import sys

from loguru import logger


def _clean_message(msg: str) -> str:
    """清理日志消息中的敏感信息"""
    import re

    patterns = [
        (r'password["\s:=]+[^\s,}]+', "password=***"),
        (r'token["\s:=]+[^\s,}]+', "token=***"),
        (r'api[_-]?key["\s:=]+[^\s,}]+', "api_key=***"),
    ]
    for pattern, replacement in patterns:
        msg = re.sub(pattern, replacement, msg, flags=re.IGNORECASE)
    return msg


class SecurityFormatter:
    """安全日志格式化器"""

    @staticmethod
    def format(record):
        """格式化日志记录"""
        record["message"] = _clean_message(record["message"])
        return (
            "{time:YYYY-MM-DD HH:mm:ss} | "
            "{level: <8} | "
            "{name}:{function}:{line} - "
            "{message}\n{exception}"
        )


def setup_secure_logger():
    """配置安全日志"""
    logger.remove()
    logger.add(
        sys.stderr,
        format=SecurityFormatter.format(),
        level="INFO",
    )


setup_secure_logger()
