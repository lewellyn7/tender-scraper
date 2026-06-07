"""全局配置管理"""
import os
from typing import Optional


class Settings:
    FORCE_HTTPS = False
    """应用配置"""
    
    def __init__(self):
        # 部署模式：self(自用) | team(团队)
        self._deployment_mode = os.getenv("DEPLOYMENT_MODE", "team")
        self._env = os.getenv("ENV", "development")  # 2026-06-05 P0-9
        self._validate_deployment_mode()
        self._validate_production_safety()
    
    def _validate_deployment_mode(self):
        """验证部署模式"""
        if self._deployment_mode not in ("self", "team"):
            raise ValueError("DEPLOYMENT_MODE must be 'self' or 'team'")

    def _validate_production_safety(self):
        """2026-06-05 P0-9: 禁止 self-mode 跑在 production — 会裸奔
        self 模式依赖 admin-fallback 永真，生产环境严禁"""
        if self._deployment_mode == "self" and self._env == "production":
            raise RuntimeError(
                "DEPLOYMENT_MODE=self 在 production 环境被禁（admin-fallback 永真、"
                "所有 API 端点对未认证用户开放）。生产请改 DEPLOYMENT_MODE=team。"
            )
    
    @property
    def deployment_mode(self) -> str:
        """获取部署模式"""
        return self._deployment_mode
    
    @property
    def is_self_mode(self) -> bool:
        """是否为自用模式"""
        return self._deployment_mode == "self"
    
    @property
    def is_team_mode(self) -> bool:
        """是否为团队模式"""
        return self._deployment_mode == "team"

    @property
    def env(self) -> str:
        """2026-06-05 P0-9: 当前环境 (development/staging/production)"""
        return self._env
    
    # 默认管理员配置（自用模式）
    @property
    def default_admin_username(self) -> str:
        return os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
    
    @property
    def default_admin_password(self) -> str:
        pwd = os.getenv("DEFAULT_ADMIN_PASSWORD")
        if not pwd:
            raise ValueError(
                "DEFAULT_ADMIN_PASSWORD environment variable is not set. "
                "Production deployment requires explicit admin password. "
                "Hint: set it in docker secrets or .env file."
            )
        return pwd
    
    @property
    def default_admin_display_name(self) -> str:
        return os.getenv("DEFAULT_ADMIN_DISPLAY_NAME", "系统管理员")


# 全局单例
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """获取配置单例"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings():
    """重新加载配置（用于测试或热重载）"""
    global _settings
    _settings = Settings()
    return _settings

# 模块级实例，供中间件等直接导入
settings = get_settings()
