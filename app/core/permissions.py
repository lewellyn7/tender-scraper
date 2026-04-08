"""用户权限管理系统"""

import json
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from loguru import logger

ADMIN_FILE = Path(__file__).parent.parent.parent / "config" / "admin_users.json"


class Role(Enum):
    GUEST = "guest"
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


class Permission(Enum):
    SYSTEM_CONFIG = "system:config"
    SYSTEM_MANAGE_USERS = "system:manage_users"
    SYSTEM_VIEW_LOGS = "system:view_logs"
    SCRAPE_TRIGGER = "scrape:trigger"
    SCRAPE_STOP = "scrape:stop"
    SCRAPE_VIEW_STATUS = "scrape:view_status"
    DATA_VIEW = "data:view"
    DATA_EXPORT = "data:export"
    DATA_DELETE = "data:delete"
    DATA_VIEW_ANALYTICS = "data:view_analytics"
    FAVORITES_VIEW = "favorites:view"
    FAVORITES_ADD = "favorites:add"
    FAVORITES_REMOVE = "favorites:remove"
    FAVORITES_UPDATE = "favorites:update"
    NOTIF_CONFIG = "notif:config"
    NOTIF_TEST = "notif:test"


ROLE_PERMISSIONS: Dict[Role, Set[Permission]] = {
    Role.GUEST: {Permission.SCRAPE_VIEW_STATUS, Permission.DATA_VIEW},
    Role.VIEWER: {
        Permission.SCRAPE_VIEW_STATUS,
        Permission.DATA_VIEW,
        Permission.DATA_VIEW_ANALYTICS,
        Permission.FAVORITES_VIEW,
    },
    Role.OPERATOR: {
        Permission.SCRAPE_VIEW_STATUS,
        Permission.SCRAPE_TRIGGER,
        Permission.DATA_VIEW,
        Permission.DATA_VIEW_ANALYTICS,
        Permission.DATA_EXPORT,
        Permission.FAVORITES_VIEW,
        Permission.FAVORITES_ADD,
        Permission.FAVORITES_REMOVE,
        Permission.FAVORITES_UPDATE,
        Permission.NOTIF_TEST,
    },
    Role.ADMIN: set(Permission),
}


class User:
    def __init__(
        self,
        user_id: str,
        role: Role = Role.VIEWER,
        permissions: Set[Permission] = None,
        name: str = None,
        telegram_id: str = None,
        enabled: bool = True,
    ):
        self.user_id = user_id
        self.role = role
        self.permissions = permissions or ROLE_PERMISSIONS.get(role, set()).copy()
        self.name = name
        self.telegram_id = telegram_id or user_id
        self.enabled = enabled

    def has_permission(self, permission: Permission) -> bool:
        return self.enabled and permission in self.permissions

    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "role": self.role.value,
            "permissions": [p.value for p in self.permissions],
            "name": self.name,
            "enabled": self.enabled,
        }


class PermissionConfig:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.config_file = ADMIN_FILE
        self._users: Dict[str, User] = {}
        self._admins: Set[str] = set()
        self._load_config()

    def _load_config(self):
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                users_data = data.get("users", [])
                for u in users_data:
                    try:
                        role = Role(u.get("role", "viewer"))
                    except ValueError:
                        role = Role.VIEWER
                    user = User(
                        user_id=u.get("user_id", ""),
                        role=role,
                        name=u.get("name"),
                        enabled=u.get("enabled", True),
                    )
                    self._users[user.user_id] = user
                self._admins = set(data.get("admin_users", []))
            except Exception as e:
                logger.error(f"加载权限配置失败: {e}")
                self._users = {}
                self._admins = set()
        else:
            self._users = {}
            self._admins = set()
            self._save_config()

    def _save_config(self):
        users_data = [user.to_dict() for user in self._users.values()]
        data = {
            "users": users_data,
            "admin_users": list(self._admins),
            "description": "用户权限配置",
        }
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_user(self, user_id: str) -> Optional[User]:
        return self._users.get(user_id)

    def add_user(self, user: User) -> bool:
        if user.user_id in self._users:
            return False
        self._users[user.user_id] = user
        self._save_config()
        return True

    def list_users(self) -> List[User]:
        return list(self._users.values())

    def is_admin(self, user_id: str) -> bool:
        # 优先从数据库读取用户角色，避免硬编码依赖
        try:
            from app.database.db import get_db

            db_user = get_db().get_user_by_id(user_id)
            if db_user and db_user.get("role") == "admin":
                return True
        except Exception as e:
            logger.warning(f"数据库管理员检查失败: {e}")
        # 备用: 检查配置文件中的 admin_users (向后兼容)
        return user_id in self._admins


# 全局实例
_perm_config: Optional[PermissionConfig] = None


def get_perm_config() -> PermissionConfig:
    global _perm_config
    if _perm_config is None:
        _perm_config = PermissionConfig()
    return _perm_config


def check_permission(user_id: str, permission: Permission) -> bool:
    """Check if user_id has the given permission.

    Unknown users are always denied — no fallback to admin check.
    This prevents unauthenticated or unregistered users from gaining
    access through misconfigured database entries.
    """
    user = get_perm_config().get_user(user_id)
    if not user:
        # Deny by default: unknown users must be explicitly registered
        return False
    return user.has_permission(permission)


def require_permission(permission: Permission):
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = kwargs.get("request")
            user_id = None
            if request:
                user_id = getattr(request.state, "user_id", None)
                if not user_id:
                    user_id = request.headers.get("X-User-ID")
            if not user_id:
                from fastapi import HTTPException

                raise HTTPException(status_code=401, detail="未认证")
            if not check_permission(user_id, permission):
                from fastapi import HTTPException

                raise HTTPException(status_code=403, detail=f"缺少权限: {permission.value}")
            return await func(*args, **kwargs)

        return wrapper

    return decorator
