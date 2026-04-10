#!/usr/bin/env python3
"""
config.py - 采集系统配置管理
===========================
- 环境变量加载 (.env)
- YAML 配置解析
- 默认值与配置校验
- 多环境支持 (dev/staging/prod)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── 路径 ─────────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent.parent.resolve()
DEFAULT_ENV_FILE = ROOT_DIR / ".env"

# ── 加载 dotenv ───────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    if DEFAULT_ENV_FILE.exists():
        load_dotenv(DEFAULT_ENV_FILE, override=True)
except ImportError:
    pass  # dotenv not installed, rely on system env vars

# ── 枚举 ───────────────────────────────────────────────────────────────────────
class LogLevel(str):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


# ── 基础配置 ─────────────────────────────────────────────────────────────────
@dataclass
class BrowserConfig:
    """浏览器/Playwright 配置"""
    headless: bool = True
    stealth: bool = True
    slow_mo: int = 0           # ms，调试用减速
    timeout: int = 30000        # ms
    viewport_width: int = 1280
    viewport_height: int = 800
    proxy: Optional[str] = None  # http://user:pass@host:port


@dataclass
class CrawlerConfig:
    """爬虫基础配置"""
    max_retries: int = 3
    retry_delay_base: float = 2.0  # seconds
    rate_limit_per_second: float = 5.0
    rate_limit_burst: int = 10
    max_concurrent_requests: int = 20
    request_timeout: int = 30  # seconds


@dataclass
class DatabaseConfig:
    """PostgreSQL 配置"""
    url: str = "postgresql://lewellyn:lewellyn@localhost:5432/procurement"
    pool_min_size: int = 2
    pool_max_size: int = 10
    command_timeout: int = 30


@dataclass
class RedisConfig:
    """Redis 配置"""
    url: str = "redis://localhost:6379/0"
    cache_ttl_default: int = 3600
    cache_ttl_harvest: int = 86400
    lock_timeout: int = 30
    lock_blocking_timeout: int = 10


@dataclass
class SchedulerConfig:
    """智能调度器配置"""
    priority_decay_factor: float = 0.95
    priority_urgency_weight: float = 2.0
    priority_recency_weight: float = 1.5
    priority_success_weight: float = 1.0
    priority_stability_weight: float = 0.5
    min_interval_seconds: float = 5.0
    max_interval_seconds: float = 3600.0
    backoff_base: float = 60.0
    backoff_max: float = 900.0


@dataclass
class ExceptionHandlerConfig:
    """异常处理配置"""
    rate_limit_cooldown: int = 300   # 5min
    ban_cooldown: int = 900          # 15min
    max_quick_retries: int = 3
    alert_threshold: int = 5         # 连续异常次数达到此值则告警


@dataclass
class OutputConfig:
    """输出配置"""
    log_dir: str = "/home/lewellyn/.openclaw/workspace/logs/procurement"
    output_dir: str = "/home/lewellyn/.openclaw/workspace/output"
    excel_enabled: bool = True


# ── 全局配置 ─────────────────────────────────────────────────────────────────
@dataclass
class SystemConfig:
    """系统全局配置"""
    env: str = "development"  # development | staging | production
    log_level: LogLevel = LogLevel.INFO
    log_dir: str = "/home/lewellyn/.openclaw/workspace/logs"
    data_dir: str = "/home/lewellyn/.openclaw/workspace/data"

    # 子模块配置
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    crawler: CrawlerConfig = field(default_factory=CrawlerConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    exception_handler: ExceptionHandlerConfig = field(default_factory=ExceptionHandlerConfig)
    output: OutputConfig = field(default_factory=OutputConfig)

    @classmethod
    def from_env(cls) -> "SystemConfig":
        """从环境变量构建配置"""
        cfg = cls()
        cfg.env = os.getenv("ENV", "development")
        cfg.log_level = LogLevel(os.getenv("LOG_LEVEL", "INFO"))
        cfg.log_dir = os.getenv("LOG_DIR", cfg.log_dir)
        cfg.data_dir = os.getenv("DATA_DIR", cfg.data_dir)

        # Browser
        cfg.browser.headless = os.getenv("BROWSER_HEADLESS", "true").lower() != "false"
        cfg.browser.stealth = os.getenv("BROWSER_STEALTH", "true").lower() != "false"
        cfg.browser.slow_mo = int(os.getenv("BROWSER_SLOW_MO", "0"))
        cfg.browser.timeout = int(os.getenv("BROWSER_TIMEOUT", "30000"))
        cfg.browser.proxy = os.getenv("BROWSER_PROXY")

        # Crawler
        cfg.crawler.max_retries = int(os.getenv("CRAWLER_MAX_RETRIES", "3"))
        cfg.crawler.rate_limit_per_second = float(os.getenv("RATE_LIMIT_PER_SECOND", "5.0"))
        cfg.crawler.max_concurrent_requests = int(os.getenv("MAX_CONCURRENT", "20"))

        # Database
        cfg.database.url = os.getenv(
            "DATABASE_URL",
            "postgresql://lewellyn:lewellyn@localhost:5432/procurement"
        )

        # Redis
        cfg.redis.url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

        return cfg

    @classmethod
    def from_yaml(cls, path: str) -> "SystemConfig":
        """从 YAML 文件加载配置"""
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        cfg = cls()
        # 浅层合并，可按需深化
        for section in ("browser", "crawler", "database", "redis",
                        "scheduler", "exception_handler", "output"):
            if section in data:
                subsection = getattr(cfg, section)
                for k, v in data[section].items():
                    if hasattr(subsection, k):
                        setattr(subsection, k, v)
        return cfg

    def apply_env_overrides(self) -> None:
        """用环境变量覆盖 YAML 配置（环境变量优先）"""
        # 数据库
        if os.getenv("DATABASE_URL"):
            self.database.url = os.getenv("DATABASE_URL")
        # Redis
        if os.getenv("REDIS_URL"):
            self.redis.url = os.getenv("REDIS_URL")
        # 日志
        if os.getenv("LOG_LEVEL"):
            self.log_level = LogLevel(os.getenv("LOG_LEVEL"))
        # 代理
        if os.getenv("BROWSER_PROXY"):
            self.browser.proxy = os.getenv("BROWSER_PROXY")


# ── 便捷单例 ──────────────────────────────────────────────────────────────────
_config_cache: Optional[SystemConfig] = None

def get_config(env_file: Optional[str] = None) -> SystemConfig:
    """获取全局配置单例"""
    global _config_cache
    if _config_cache is None:
        _config_cache = SystemConfig.from_env()
        if env_file and Path(env_file).exists():
            _config_cache = SystemConfig.from_yaml(env_file)
            _config_cache.apply_env_overrides()
        else:
            _config_cache.apply_env_overrides()
    return _config_cache


def reset_config() -> None:
    """重置配置缓存（用于测试）"""
    global _config_cache
    _config_cache = None
