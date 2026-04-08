"""app.core.harvest — 采集系统核心模块

包含：反检测、人类行为引擎、智能调度、异常处理、缓存、配置

反检测子模块 (app.core.harvest.anti_detect):
  - fingerprints.py : 浏览器指纹生成
  - canvas.py      : Canvas 噪声注入 + WebGL 参数伪造
  - webgl.py       : WebGL 常量
  - tls.py         : TLS 指纹模拟 (JA3/JA4)
  - dns.py         : DNS 泄漏防护 (DoH/DoT)
  - behavior.py    : 人类行为模拟 + 自适应学习引擎
  - manager.py     : AntiDetectManager 统一入口 + Playwright 适配器
"""

from app.core.harvest.anti_detect import (
    AdaptiveLearningEngine,
    AntiDetectManager,
    CanvasNoiseInjector,
    DNSLeakProtector,
    FingerprintProfile,
    HumanBehaviorSimulator,
    PlaywrightAntiDetectAdapter,
    TLSFingerprintForCurl,
    TLSFingerprintSimulator,
)
from app.core.harvest.human_behavior_engine import HumanBehaviorEngine
from app.core.harvest.smart_scheduler import (
    AdaptiveIntervalManager,
    CrawlTask,
    DynamicPriorityEngine,
    SmartScheduler,
    TaskStatus,
)
from app.core.harvest.exception_handler import (
    AnomalyClassifier,
    AnomalyType,
    ExceptionStateMachine,
)
from app.core.harvest.cache_manager import CacheManager, RedisManager
from app.core.harvest.config import SystemConfig, get_config

__all__ = [
    # anti_detect
    "FingerprintProfile",
    "CanvasNoiseInjector",
    "TLSFingerprintSimulator",
    "TLSFingerprintForCurl",
    "DNSLeakProtector",
    "HumanBehaviorSimulator",
    "AdaptiveLearningEngine",
    "AntiDetectManager",
    "PlaywrightAntiDetectAdapter",
    # human_behavior_engine
    "HumanBehaviorEngine",
    # smart_scheduler
    "SmartScheduler",
    "DynamicPriorityEngine",
    "AdaptiveIntervalManager",
    "CrawlTask",
    "TaskStatus",
    # exception_handler
    "ExceptionStateMachine",
    "AnomalyClassifier",
    "AnomalyType",
    # cache_manager
    "RedisManager",
    "CacheManager",
    # config
    "get_config",
    "SystemConfig",
]
