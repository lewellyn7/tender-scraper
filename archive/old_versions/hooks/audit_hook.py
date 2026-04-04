#!/usr/bin/env python3
"""
审计 Hook 系统核心模块
记录所有工具调用到 audit.log，支持日志轮转和高效查询

日志格式（符合企业审计规范）：
时间戳 | 会话ID | 工具名 | 参数哈希 | 执行结果 | 耗时(ms) | 详细信息
"""

import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional
import uuid


class AuditLogger:
    """审计日志记录器"""
    
    # 日志格式：时间戳 | 会话ID | 工具名 | 参数哈希 | 执行结果 | 耗时(ms) | 详细信息
    LOG_FORMAT = "%(asctime)s | %(session_id)s | %(tool_name)s | %(params_hash)s | %(result_status)s | %(duration_ms)d | %(details)s"
    DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
    
    def __init__(
        self,
        log_dir: str = "logs",
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 10,
        rotation: str = "size",  # "size" or "daily"
    ):
        """
        初始化审计日志记录器
        
        Args:
            log_dir: 日志目录
            max_bytes: 单个日志文件最大大小（字节）
            backup_count: 保留的日志文件数量
            rotation: 轮转方式 "size"（按大小）或 "daily"（按天）
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.log_file = self.log_dir / "audit.log"
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.rotation = rotation
        
        self.logger = self._setup_logger()
        self.session_id = self._generate_session_id()
        self._call_stack: Dict[str, datetime] = {}  # 跟踪调用开始时间
    
    def _generate_session_id(self) -> str:
        """生成唯一会话ID"""
        return f"session-{uuid.uuid4().hex[:8]}"
    
    def _setup_logger(self) -> logging.Logger:
        """配置日志记录器"""
        logger = logging.getLogger("audit")
        logger.setLevel(logging.INFO)
        
        # 清除现有处理器
        logger.handlers.clear()
        
        if self.rotation == "size":
            handler = RotatingFileHandler(
                self.log_file,
                maxBytes=self.max_bytes,
                backupCount=self.backup_count,
                encoding="utf-8"
            )
        else:  # daily
            handler = TimedRotatingFileHandler(
                self.log_file,
                when="midnight",
                interval=1,
                backupCount=self.backup_count,
                encoding="utf-8"
            )
        
        formatter = logging.Formatter(self.LOG_FORMAT, datefmt=self.DATE_FORMAT)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        return logger
    
    def _compute_params_hash(self, params: Dict[str, Any]) -> str:
        """
        计算参数哈希值（SHA256前16位）
        
        Args:
            params: 工具调用参数
            
        Returns:
            参数哈希字符串
        """
        try:
            params_str = json.dumps(params, sort_keys=True, default=str)
            return hashlib.sha256(params_str.encode()).hexdigest()[:16]
        except Exception:
            return "hash_error"
    
    def before_call(self, tool_name: str, params: Dict[str, Any]) -> str:
        """
        记录工具调用开始
        
        Args:
            tool_name: 工具名称
            params: 调用参数
            
        Returns:
            调用ID（用于匹配结束记录）
        """
        call_id = f"{tool_name}-{uuid.uuid4().hex[:8]}"
        self._call_stack[call_id] = datetime.now()
        
        # 记录开始（状态为 STARTED）
        self.logger.info(
            "",
            extra={
                "session_id": self.session_id,
                "tool_name": tool_name,
                "params_hash": self._compute_params_hash(params),
                "result_status": "STARTED",
                "duration_ms": 0,
                "details": json.dumps({"call_id": call_id, "params_preview": self._preview_params(params)})
            }
        )
        
        return call_id
    
    def after_call(
        self,
        call_id: str,
        tool_name: str,
        params: Dict[str, Any],
        result: Any,
        success: bool = True,
        error: Optional[str] = None
    ) -> None:
        """
        记录工具调用结束
        
        Args:
            call_id: 调用ID
            tool_name: 工具名称
            params: 调用参数
            result: 执行结果
            success: 是否成功
            error: 错误信息（如果失败）
        """
        start_time = self._call_stack.pop(call_id, None)
        if start_time:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        else:
            duration_ms = 0
        
        result_status = "SUCCESS" if success else "FAILED"
        details = {
            "call_id": call_id,
            "result_preview": self._preview_result(result),
        }
        if error:
            details["error"] = error
        
        self.logger.info(
            "",
            extra={
                "session_id": self.session_id,
                "tool_name": tool_name,
                "params_hash": self._compute_params_hash(params),
                "result_status": result_status,
                "duration_ms": duration_ms,
                "details": json.dumps(details)
            }
        )
    
    def _preview_params(self, params: Dict[str, Any], max_len: int = 200) -> str:
        """生成参数预览（截断敏感信息）"""
        preview = {}
        for k, v in params.items():
            if isinstance(v, str) and len(v) > 50:
                preview[k] = v[:50] + "..."
            elif k in ["password", "token", "api_key", "secret"]:
                preview[k] = "***REDACTED***"
            else:
                preview[k] = v
        return json.dumps(preview, default=str)[:max_len]
    
    def _preview_result(self, result: Any, max_len: int = 200) -> str:
        """生成结果预览"""
        try:
            result_str = str(result)
            return result_str[:max_len] + "..." if len(result_str) > max_len else result_str
        except Exception:
            return "<non-serializable>"


class OpenClawAuditHook:
    """
    OpenClaw 审计 Hook 集成示例
    
    使用方法：
    1. 在 OpenClaw 配置中注册此 Hook
    2. 所有工具调用将自动记录到审计日志
    """
    
    def __init__(self, log_dir: str = "logs", rotation: str = "size"):
        self.audit_logger = AuditLogger(log_dir=log_dir, rotation=rotation)
    
    async def before_tool_call(self, tool_name: str, params: Dict[str, Any]) -> str:
        """
        工具调用前 Hook
        
        Args:
            tool_name: 工具名称
            params: 调用参数
            
        Returns:
            上下文对象（传递给 after_tool_call）
        """
        call_id = self.audit_logger.before_call(tool_name, params)
        return call_id
    
    async def after_tool_call(
        self,
        call_id: str,
        tool_name: str,
        params: Dict[str, Any],
        result: Any,
        success: bool = True,
        error: Optional[str] = None
    ) -> None:
        """
        工具调用后 Hook
        
        Args:
            call_id: 上下文对象（来自 before_tool_call）
            tool_name: 工具名称
            params: 调用参数
            result: 执行结果
            success: 是否成功
            error: 错误信息
        """
        self.audit_logger.after_call(call_id, tool_name, params, result, success, error)


def create_audit_hook(log_dir: str = "logs") -> OpenClawAuditHook:
    """
    创建审计 Hook 实例
    
    Args:
        log_dir: 日志目录
        
    Returns:
        OpenClawAuditHook 实例
    """
    return OpenClawAuditHook(log_dir=log_dir)


# 装饰器方式使用
def audit_call(tool_name: str):
    """
    审计装饰器，用于包装工具函数
    
    Args:
        tool_name: 工具名称
        
    Usage:
        @audit_call("write_file")
        def write_file(path: str, content: str):
            ...
    """
    def decorator(func):
        audit_logger = AuditLogger()
        
        def wrapper(*args, **kwargs):
            params = {"args": args, "kwargs": kwargs}
            call_id = audit_logger.before_call(tool_name, params)
            
            try:
                result = func(*args, **kwargs)
                audit_logger.after_call(call_id, tool_name, params, result, success=True)
                return result
            except Exception as e:
                audit_logger.after_call(call_id, tool_name, params, None, success=False, error=str(e))
                raise
        
        return wrapper
    return decorator


if __name__ == "__main__":
    # 测试示例
    audit = AuditLogger(log_dir="logs", rotation="size")
    
    # 模拟工具调用
    params = {"path": "/tmp/test.txt", "content": "Hello, World!"}
    call_id = audit.before_call("write_file", params)
    
    import time
    time.sleep(0.1)  # 模拟执行耗时
    
    audit.after_call(call_id, "write_file", params, {"status": "written"}, success=True)
    
    print(f"审计日志已写入: {audit.log_file}")
