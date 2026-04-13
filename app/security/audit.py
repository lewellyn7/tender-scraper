"""审计日志模块

非阻塞异步写入审计日志，支持 SQLite 和 PostgreSQL。
使用后台线程队列，不阻塞主流程。
"""
import json
import queue
import threading
import time
from datetime import datetime
from typing import Optional

from loguru import logger

# 事件类型常量
EVENT_LOGIN_SUCCESS = "login_success"
EVENT_LOGIN_FAILURE = "login_failure"
EVENT_LOGOUT = "logout"
EVENT_DATA_EXPORT = "data_export"
EVENT_DATA_DELETE = "data_delete"
EVENT_CONFIG_CHANGE = "config_change"
EVENT_CRAWL_STARTED = "crawl_started"
EVENT_CRAWL_COMPLETED = "crawl_completed"
EVENT_CRAWL_FAILED = "crawl_failed"
EVENT_USER_CREATED = "user_created"
EVENT_USER_DELETED = "user_deleted"
EVENT_PASSWORD_CHANGED = "password_changed"


class AuditLogWriter:
    """审计日志异步写入器（后台线程）"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._queue: queue.Queue = queue.Queue()
        self._shutdown = False
        self._thread = threading.Thread(target=self._writer_loop, daemon=True, name="AuditLogWriter")
        self._thread.start()
        self._initialized = True
        logger.info("[AuditLog] 已启动")

    def _writer_loop(self):
        """后台写入循环"""
        batch = []
        while not self._shutdown or not self._queue.empty():
            try:
                item = self._queue.get(timeout=1)
                batch.append(item)
                while len(batch) < 100 and not self._queue.empty():
                    try:
                        batch.append(self._queue.get_nowait())
                    except queue.Empty:
                        break
                if batch:
                    self._write_batch(batch)
                    batch.clear()
            except queue.Empty:
                if batch:
                    self._write_batch(batch)
                    batch.clear()
        # drain remaining
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if batch:
            self._write_batch(batch)

    def _write_batch(self, batch: list):
        """批量写入审计日志"""
        import os
        from pathlib import Path

        from app.database.db import USE_PG

        if not batch:
            return

        if USE_PG:
            self._write_batch_pg(batch)
        else:
            self._write_batch_sqlite(batch)

    def _write_batch_pg(self, batch: list):
        """PostgreSQL 批量写入"""
        try:
            import psycopg2
            from app.database.db import DATABASE_URL, _get_pg_pool

            pool = _get_pg_pool()
            conn = pool.getconn()
            try:
                cursor = conn.cursor()
                for record in batch:
                    cursor.execute(
                        """
                        INSERT INTO audit_logs (event, user_id, ip_address, user_agent, resource, result, details)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            record["event"],
                            record.get("user_id"),
                            record.get("ip_address"),
                            record.get("user_agent"),
                            record.get("resource"),
                            record.get("result"),
                            json.dumps(record.get("details") or {}, ensure_ascii=False),
                        ),
                    )
                conn.commit()
                cursor.close()
            except Exception as e:
                conn.rollback()
                logger.error(f"[AuditLog] PG batch write failed: {e}")
            finally:
                pool.putconn(conn)
        except Exception as e:
            logger.error(f"[AuditLog] PG write error: {e}")

    def _write_batch_sqlite(self, batch: list):
        """SQLite 批量写入（同步）"""
        try:
            import sqlite3
            from pathlib import Path

            db_path = Path(__file__).parent.parent.parent / "config" / "tender_scraper.db"
            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            cursor = conn.cursor()
            for record in batch:
                cursor.execute(
                    """
                    INSERT INTO audit_logs (event, user_id, ip_address, user_agent, resource, result, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["event"],
                        record.get("user_id"),
                        record.get("ip_address"),
                        record.get("user_agent"),
                        record.get("resource"),
                        record.get("result"),
                        json.dumps(record.get("details") or {}, ensure_ascii=False),
                    ),
                )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"[AuditLog] SQLite batch write failed: {e}")

    def enqueue(self, event: str, user_id: str = None, ip_address: str = None,
                user_agent: str = None, resource: str = None,
                result: str = "success", details: dict = None):
        """将审计日志入队（非阻塞）"""
        self._queue.put_nowait({
            "event": event,
            "user_id": user_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "resource": resource,
            "result": result,
            "details": details,
            "timestamp": datetime.now().isoformat(),
        })

    def shutdown(self):
        self._shutdown = True
        self._thread.join(timeout=5)


# 全局单例
_audit_writer: Optional[AuditLogWriter] = None


def get_audit_writer() -> AuditLogWriter:
    global _audit_writer
    if _audit_writer is None:
        _audit_writer = AuditLogWriter()
    return _audit_writer


def write_audit_log(
    event: str,
    user_id: str = None,
    ip_address: str = None,
    user_agent: str = None,
    resource: str = None,
    result: str = "success",
    details: dict = None,
):
    """写入审计日志（异步，非阻塞）"""
    try:
        writer = get_audit_writer()
        writer.enqueue(
            event=event,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            resource=resource,
            result=result,
            details=details,
        )
    except Exception as e:
        logger.error(f"[AuditLog] enqueue failed: {e}")
