"""notifications 表操作 — 收藏项目关联提醒

表结构：
    id, user_id, project_id, record_id,
    project_name, info_type, record_url, record_title,
    sent_at, telegram_chat_id, telegram_msg_id, dedup_key
"""

import hashlib
import json
import os
import time
from typing import List, Optional

from loguru import logger


# 同 project 在 DEDUP_WINDOW_SEC 秒内不重复推送（5 分钟窗口）
DEDUP_WINDOW_SEC = 5 * 60


def _compute_dedup_key(user_id: str, project_id: int, info_type: str) -> str:
    """去重 key：同用户 + 同项目 + 同 info_type 视为一组（5min 内不重推）
    
    答疑补遗和中标结果分别是不同 info_type，单独去重。
    """
    raw = f"{user_id}:{project_id}:{info_type}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


class NotificationsMixin:
    """notifications 表 CRUD 操作（混入 Database 类使用）

    表作用：
    - 记录每次"收藏项目关联提醒"的发送情况
    - 支持去重（同 user+project+info_type 在 DEDUP_WINDOW_SEC 内只推一次）
    """

    def _init_notifications_table(self):
        """初始化 notifications 表（仅 SQLite；PG 由迁移脚本管理）"""
        c = self._get_conn()
        c.execute(
            """CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                project_id INTEGER NOT NULL,
                record_id INTEGER NOT NULL,
                project_name TEXT DEFAULT '',
                info_type TEXT DEFAULT '',
                record_url TEXT DEFAULT '',
                record_title TEXT DEFAULT '',
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                telegram_chat_id TEXT DEFAULT '',
                telegram_msg_id TEXT DEFAULT '',
                dedup_key TEXT DEFAULT ''
            )"""
        )
        # 去重由应用层 DEDUP_WINDOW_SEC 时间窗控制，避免 DB 端复杂 UNIQUE 约束。
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, sent_at)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_notifications_dedup ON notifications(dedup_key, sent_at)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_notifications_project ON notifications(project_id)"
        )

    def is_recently_notified(
        self, user_id: str, project_id: int, info_type: str, window_sec: int = DEDUP_WINDOW_SEC
    ) -> bool:
        """检查同 user+project+info_type 是否在 window_sec 秒内已通知过。

        时间以 UTC 为准：PG 服务器多在 UTC，sent_at DEFAULT CURRENT_TIMESTAMP 是 UTC。
        容器可能为 Asia/Shanghai — 这里全部转 UTC 对齐。
        """
        dedup_key = _compute_dedup_key(user_id, project_id, info_type)
        try:
            c = self._get_conn()
            row = c.execute(
                """SELECT sent_at FROM notifications
                   WHERE dedup_key = ?
                   ORDER BY sent_at DESC LIMIT 1""",
                (dedup_key,),
            ).fetchone()
            if not row:
                return False
            sent_at = row[0] if isinstance(row, (list, tuple)) else row["sent_at"]
            from datetime import datetime, timezone
            if isinstance(sent_at, str):
                sent_dt = datetime.strptime(sent_at[:19], "%Y-%m-%d %H:%M:%S")
            else:
                sent_dt = sent_at

            # 统一 UTC：PG CURRENT_TIMESTAMP 是 UTC（无时区信息的 naive datetime）
            if sent_dt.tzinfo is None:
                sent_dt_utc = sent_dt.replace(tzinfo=timezone.utc)
            else:
                sent_dt_utc = sent_dt.astimezone(timezone.utc)

            now_utc = datetime.now(timezone.utc)
            elapsed = (now_utc - sent_dt_utc).total_seconds()
            return elapsed < window_sec
        except Exception as e:
            logger.warning(f"is_recently_notified: {e}")
            return False

    def record_notification(
        self,
        user_id: str,
        project_id: int,
        record_id: int,
        project_name: str,
        info_type: str,
        record_url: str,
        record_title: str = "",
        telegram_chat_id: str = "",
        telegram_msg_id: str = "",
    ) -> bool:
        """记录一次通知发送。"""
        dedup_key = _compute_dedup_key(user_id, project_id, info_type)
        try:
            c = self._get_conn()
            c.execute(
                """INSERT INTO notifications
                   (user_id, project_id, record_id, project_name, info_type,
                    record_url, record_title, telegram_chat_id, telegram_msg_id, dedup_key)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    user_id,
                    project_id,
                    record_id,
                    project_name,
                    info_type,
                    record_url,
                    record_title,
                    telegram_chat_id,
                    telegram_msg_id,
                    dedup_key,
                ),
            )
            c.commit() if hasattr(c, "commit") else None
            return True
        except Exception as e:
            logger.warning(f"record_notification: {e}")
            return False

    def get_recent_notifications(self, user_id: str, limit: int = 20) -> List[dict]:
        """获取用户最近的通知。"""
        try:
            c = self._get_conn()
            rows = c.execute(
                """SELECT * FROM notifications
                   WHERE user_id = ?
                   ORDER BY sent_at DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows] if rows else []
        except Exception as e:
            logger.warning(f"get_recent_notifications: {e}")
            return []
