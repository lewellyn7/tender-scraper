"""全局配置管理"""
import os
from typing import Optional


class Settings:
    """应用配置"""
    
    def __init__(self):
        # 部署模式：self(自用) | team(团队)
        self._deployment_mode = os.getenv("DEPLOYMENT_MODE", "team")
        self._validate_deployment_mode()
    
    def _validate_deployment_mode(self):
        """验证部署模式"""
        if self._deployment_mode not in ("self", "team"):
            raise ValueError("DEPLOYMENT_MODE must be 'self' or 'team'")
    
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
