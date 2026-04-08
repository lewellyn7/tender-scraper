"""users 表操作"""

import time
from datetime import datetime
from typing import List, Optional

from loguru import logger


class UsersMixin:
    """users 表 CRUD 操作（混入 Database 类使用）"""

    def create_user(self, user_data: dict) -> str:
        try:
            c = self._get_conn()
            c.execute(
                """
                INSERT INTO users (user_id, username, password_hash, password_salt, display_name, role, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    user_data.get("user_id", f"user_{int(time.time() * 1000)}"),
                    user_data.get("username"),
                    user_data.get("password_hash"),
                    user_data.get("password_salt"),
                    user_data.get("display_name", user_data.get("username")),
                    user_data.get("role", "viewer"),
                    1 if user_data.get("enabled", True) else 0,
                    user_data.get("created_at", datetime.now().isoformat()),
                ),
            )
            c.commit()
            return user_data.get("user_id", f"user_{int(time.time() * 1000)}")
        except Exception as e:
            logger.error(f"create_user: {e}")
            return None

    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        try:
            c = self._get_conn()
            row = c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_user_by_id: {e}")
            return None

    def get_user_by_username(self, username: str) -> Optional[dict]:
        try:
            c = self._get_conn()
            row = c.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_user_by_username: {e}")
            return None

    def update_user(self, user_id: str, updates: dict):
        try:
            conn = self._get_conn()
            set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
            values = list(updates.values()) + [user_id]
            conn.execute(
                f"UPDATE users SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                values,
            )
            conn.commit()
        except Exception as e:
            logger.error(f"update_user: {e}")

    def update_user_password(self, user_id: str, pwd_hash: str, pwd_salt: str):
        try:
            conn = self._get_conn()
            conn.execute(
                "UPDATE users SET password_hash = ?, password_salt = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (pwd_hash, pwd_salt, user_id),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"update_user_password: {e}")

    def update_user_last_login(self, user_id: str):
        try:
            conn = self._get_conn()
            conn.execute(
                "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,)
            )
            conn.commit()
        except Exception as e:
            logger.error(f"update_user_last_login: {e}")

    def delete_user(self, user_id: str):
        try:
            conn = self._get_conn()
            conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            conn.commit()
        except Exception as e:
            logger.error(f"delete_user: {e}")

    def list_users_paged(
        self, page: int = 1, page_size: int = 20, role: str = None, enabled: bool = None
    ) -> tuple:
        try:
            c = self._get_conn()
            where = "WHERE 1=1"
            params = []
            if role:
                where += " AND role = ?"
                params.append(role)
            if enabled is not None:
                where += " AND enabled = ?"
                params.append(1 if enabled else 0)
            total = c.execute(f"SELECT COUNT(*) FROM users {where}", params).fetchone()[0]
            offset = (page - 1) * page_size
            rows = c.execute(
                f"SELECT * FROM users {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [page_size, offset],
            ).fetchall()
            return [dict(r) for r in rows], total
        except Exception as e:
            logger.error(f"list_users_paged: {e}")
            return [], 0

    def get_user_stats(self) -> dict:
        try:
            c = self._get_conn()
            return {
                "total": c.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                "active": c.execute("SELECT COUNT(*) FROM users WHERE enabled = 1").fetchone()[0],
                "admins": c.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0],
                "operators": c.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'operator'"
                ).fetchone()[0],
            }
        except Exception as e:
            logger.error(f"get_user_stats: {e}")
            return {"total": 0, "active": 0, "admins": 0, "operators": 0}
