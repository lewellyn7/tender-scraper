# app/core/logging_config.py
# ─────────────────────────────────────────────────────────────
# 结构化日志配置 (JSON 输出 + 敏感信息脱敏 + request_id 追踪)
# ─────────────────────────────────────────────────────────────
import copy
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger as _loguru

# ── 敏感字段模式 ──────────────────────────────────────────────
_SENSITIVE_PATTERNS = [
    re.compile(r'(password|passwd|pwd|secret|token|api_key|apikey|auth|credential)["\']?\s*[:=]\s*["\']?[^"\'\s,}]+', re.I),
]

def _redact(text: str) -> str:
    """对字符串中的敏感信息进行脱敏"""
    for pattern in _SENSITIVE_PATTERNS:
        text = pattern.sub(lambda m: f'{m.group(0).split("=")[0].strip()}=<REDACTED>', m.string)
    return text

def _sanitize_record(record: dict[str, Any]) -> dict[str, Any]:
    """Loguru interceptor：脱敏 + 字段增强"""
    record = copy.deepcopy(record)

    # 1. 时间戳归一化（ISO8601 + UTC+8）
    ts = record["time"]
    if isinstance(ts, float):
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(timezone.utc)
        record["time"] = dt.isoformat()
    else:
        record["time"] = str(ts)

    # 2. message 脱敏
    if isinstance(record.get("message"), str):
        record["message"] = _redact(record["message"])

    # 3. 异常信息脱敏
    if record.get("exception"):
        exc = record["exception"]
        if isinstance(exc, str):
            record["exception"] = _redact(exc)
        elif hasattr(exc, "value"):
            record["exception"] = _redact(str(exc.value))

    # 4. 统一字段映射（loguru → 结构化命名）
    structured = {
        "timestamp": record["time"],
        "level": record["level"].name,
        "message": record["message"],
        "source": f"{record.get('file', {}).get('path', '?')}:{record.get('line', '?')}",
        "function": record.get("function", "?"),
        "request_id": record["extra"].get("request_id", None),
        "duration_ms": record["extra"].get("duration_ms", None),
        "logger": record["logger"].get("name", "root"),
    }
    # 过滤掉 value 为 None 的字段
    return {k: v for k, v in structured.items() if v is not None}

class _StructuredSink:
    """将 Loguru 日志写入 JSON Lines 文件"""

    def __init__(self, path: str, rotation: str = "00:00", retention: str = "30 days", max_bytes: int = 100 * 1024 * 1024):
        self._log_path = Path(path)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

        # 使用 loguru 自身的文件轮转
        self._fh = None
        self._path = path
        self._rotation = rotation
        self._retention = retention
        self._max_bytes = max_bytes

    def _get_file_handler(self):
        return logging.handlers.RotatingFileHandler(
            filename=self._path,
            maxBytes=self._max_bytes,
            backupCount=30,
            encoding="utf-8",
        )

class JSONFormatter(logging.Formatter):
    """标准 logging 库的 JSON 格式化器（供其他模块兼容使用）"""

    def format(self, record: logging.LogRecord) -> str:
        import json
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).astimezone(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": _redact(record.getMessage()),
            "source": f"{record.filename}:{record.lineno}",
            "function": record.funcName,
            "logger": record.name,
        }
        if hasattr(record, "request_id"):
            entry["request_id"] = record.request_id
        if hasattr(record, "duration_ms"):
            entry["duration_ms"] = record.duration_ms
        if record.exc_text:
            entry["exception"] = _redact(record.exc_text)
        return json.dumps(entry, ensure_ascii=False)

def init_logging(log_dir: str | None = None) -> None:
    """
    初始化结构化日志系统。

    - JSON 输出到 logs/scraper.json（带轮转：100MB/文件，保留30天）
    - 控制台保留人类可读格式（带颜色）
    - 默认日志级别从环境变量 LOG_LEVEL 或 "INFO"
    """
    if log_dir is None:
        log_dir = os.environ.get("LOG_DIR", "/app/logs")

    log_file = Path(log_dir) / "scraper.json"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    level = os.environ.get("LOG_LEVEL", "INFO").upper()

    # 清除默认 handler
    _loguru.remove()

    # ── 控制台 handler（人类可读）───────────────────────────
    _loguru.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        colorize=True,
    )

    # ── JSON 文件 handler（结构化日志）────────────────────
    _loguru.add(
        str(log_file),
        level=level,
        format="{message}",
        rotation="100 MB",          # 单文件最大 100MB
        retention="30 days",       # 保留 30 天
        compression="gz",           # 压缩旧文件
        serialize=True,            # 关键！启用 JSON 序列化
        enqueue=True,              # 线程安全
        backtrace=True,
        diagnose=True,
    )

def get_logger(name: str | None = None) -> Any:
    """
    获取结构化日志记录器。

    Usage:
        log = get_logger(__name__)
        log.info("任务开始", request_id="abc-123")
        log.info("任务完成", request_id="abc-123", duration_ms=150)
    """
    if name is None:
        return _loguru
    return _loguru.bind(name=name)

class RequestIdContext:
    """请求级别上下文（自动注入 request_id）"""

    def __init__(self, request_id: str | None = None, **extra):
        self._request_id = request_id or _generate_request_id()
        self._extra = extra
        self._start_time: float | None = None

    @staticmethod
    def _generate_request_id() -> str:
        return f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{os.getpid():05d}"

    def __enter__(self):
        self._start_time = time.monotonic()
        _loguru.context = {"request_id": self._request_id, **self._extra}
        return self

    def __exit__(self, *args):
        duration_ms = int((time.monotonic() - self._start_time) * 1000) if self._start_time else None
        _loguru.bind(duration_ms=duration_ms, request_id=self._request_id).info("request_end")

    @property
    def request_id(self) -> str:
        return self._request_id
