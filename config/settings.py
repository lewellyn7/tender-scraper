"""项目配置"""
from typing import List

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """招投标采集系统配置"""

    # 基础配置
    PROJECT_NAME: str = "重庆市公共资源交易采集系统"
    TIMEZONE: str = "Asia/Shanghai"

    # 目标网站
    TARGET_URL: str = "https://www.cqggzy.com/"

    # 采集关键词 (更通用的词汇以确保有匹配)
    KEYWORDS: List[str] = [
        "智慧", "智能", "数字化", "信息化", "系统", "平台",
        "软件", "服务", "数据", "网络", "建设", "改造"
    ]

    # 排除关键词
    EXCLUDE_KEYWORDS: List[str] = [
        "流标", "终止", "废标", "中标公告", "成交公告", "结果公告"
    ]

    # 采集时间范围 (小时)
    TIME_RANGE_HOURS: int = 24

    # 输出配置
    OUTPUT_DIR: str = "output"

    # 浏览器配置
    HEADLESS: bool = True
    SLOW_MO: int = 100

    # 重试配置
    MAX_RETRIES: int = 3
    RETRY_DELAY: int = 5

    # n8n 集成配置
    N8N_WEBHOOK_URL: str = ""
    N8N_TRIGGER_COLLECTION: str = ""
    N8N_TRIGGER_NOTIFY: str = ""
    N8N_WEBHOOK_KEY: str = ""

    # Pydantic v2 config
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # 忽略 .env 中未定义的字段
    )


settings = Settings()
