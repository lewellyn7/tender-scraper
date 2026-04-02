from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    # 基础配置
    PROJECT_NAME: str = "重庆市政府采购采集系统"
    TIMEZONE: str = "Asia/Shanghai"
    
    # 目标网站
    TARGET_URL: str = "https://www.ccgp-chongqing.gov.cn/"
    
    # 采集关键词 (支持 OR 逻辑)
    KEYWORDS: List[str] = [
        "智能化",
        "音视频",
        "AI",
        "人工智能",
        "智能体",
        "大模型",
        "机器学习",
        "深度学习",
        "NLP",
        "自然语言处理",
        "计算机视觉",
        "人脸识别",
        "语音识别"
    ]
    
    # 排除关键词
    EXCLUDE_KEYWORDS: List[str] = [
        "流标",
        "终止",
        "废标"
    ]
    
    # 采集时间范围 (小时)
    TIME_RANGE_HOURS: int = 24
    
    # 输出配置
    OUTPUT_DIR: str = "output"
    
    # 浏览器配置
    HEADLESS: bool = True  # 生产环境设为 True
    SLOW_MO: int = 100     # 操作延迟 (ms),模拟真人
    
    class Config:
        env_file = ".env"

settings = Settings()
