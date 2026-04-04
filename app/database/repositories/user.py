"""用户仓储"""

import hashlib
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .base import BaseRepository


class UserRepository(BaseRepository):
    """用户数据仓储"""

    def __init__(self):
        super().__init__("users")

    def get_by_username(self, username: str) -> Optional[Dict]:
        """根据用户名获取用户"""
        return self.get_by_id("username", username)

    def get_by_role(self, role: str) -> List[Dict]:
        """根据角色获取用户列表"""
        rows = self.conn.execute(
            "SELECT * FROM users WHERE role = ? ORDER BY created_at DESC", (role,)
        ).fetchall()
        return [dict(r) for r in rows]

    def create(self, user_data: Dict) -> str:
        """创建用户"""
        user_id = user_data.get("user_id", f"user_{int(time.time() * 1000)}")
        try:
            self.conn.execute(
                """INSERT INTO users
                   (user_id, username, password_hash, password_salt, display_name, role, enabled, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    user_data["username"],
                    user_data["password_hash"],
                    user_data["password_salt"],
                    user_data.get("display_name", user_data["username"]),
                    user_data.get("role", "viewer"),
                    1 if user_data.get("enabled", True) else 0,
                    user_data.get("created_at", datetime.now().isoformat()),
                ),
            )
            self.conn.commit()
            return user_id
        except Exception as e:
            self.db.logger.error(f"Create user error: {e}")
            return None

    def update_password(self, user_id: str, pwd_hash: str, pwd_salt: str) -> bool:
        """更新密码"""
        try:
            self.conn.execute(
                """UPDATE users
                   SET password_hash = ?, password_salt = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE user_id = ?""",
                (pwd_hash, pwd_salt, user_id),
            )
            self.conn.commit()
            return True
        except Exception as e:
            self.db.logger.error(f"Update password error: {e}")
            return False

    def update_last_login(self, user_id: str) -> bool:
        """更新最后登录时间"""
        try:
            self.conn.execute(
                "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,)
            )
            self.conn.commit()
            return True
        except Exception as e:
            self.db.logger.error(f"Update last login error: {e}")
            return False

    def verify_password(self, username: str, password: str) -> Optional[Dict]:
        """验证密码"""
        user = self.get_by_username(username)
        if not user:
            return None

        salt = user["password_salt"]
        pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()

        if pwd_hash == user["password_hash"]:
            return user
        return None

    def list_paged(
        self, page: int = 1, page_size: int = 20, role: str = None, enabled: bool = None
    ) -> Tuple[List[Dict], int]:
        """分页获取用户列表"""
        conditions = ["1=1"]
        params = []

        if role:
            conditions.append("role = ?")
            params.append(role)

        if enabled is not None:
            conditions.append("enabled = ?")
            params.append(1 if enabled else 0)

        where = " AND ".join(conditions)

        total = self.conn.execute(f"SELECT COUNT(*) FROM users WHERE {where}", params).fetchone()[0]

        offset = (page - 1) * page_size
        rows = self.conn.execute(
            f"""SELECT * FROM users WHERE {where}
               ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            params + [page_size, offset],
        ).fetchall()

        return [dict(r) for r in rows], total
