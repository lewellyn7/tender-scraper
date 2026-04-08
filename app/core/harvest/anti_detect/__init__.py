"""反检测子模块

结构：
- fingerprints.py : 浏览器指纹生成与管理
- canvas.py      : Canvas 指纹噪声注入 + WebGL 参数伪造
- webgl.py       : WebGL 指纹常量
- tls.py         : TLS 指纹模拟 (JA3/JA4) + curl_cffi 集成
- dns.py         : DNS 泄漏防护 (DoH/DoT)
- behavior.py    : 人类行为模拟 + 自适应学习引擎
- manager.py     : AntiDetectManager 统一入口 + Playwright 适配器
"""

from app.core.harvest.anti_detect.behavior import (
    AdaptiveLearningEngine,
    HumanBehaviorSimulator,
)
from app.core.harvest.anti_detect.canvas import CanvasNoiseInjector
from app.core.harvest.anti_detect.dns import DNSLeakProtector
from app.core.harvest.anti_detect.fingerprints import FingerprintProfile
from app.core.harvest.anti_detect.manager import (
    AntiDetectManager,
    PlaywrightAntiDetectAdapter,
)
from app.core.harvest.anti_detect.tls import TLSFingerprintForCurl, TLSFingerprintSimulator
from app.core.harvest.anti_detect.webgl import (
    FAKE_GPU_POOL,
    UNMASKED_RENDERER_WEBGL,
    UNMASKED_VENDOR_WEBGL,
)

__all__ = [
    # fingerprints
    "FingerprintProfile",
    # canvas / webgl
    "CanvasNoiseInjector",
    "UNMASKED_VENDOR_WEBGL",
    "UNMASKED_RENDERER_WEBGL",
    "FAKE_GPU_POOL",
    # tls
    "TLSFingerprintSimulator",
    "TLSFingerprintForCurl",
    # dns
    "DNSLeakProtector",
    # behavior
    "HumanBehaviorSimulator",
    "AdaptiveLearningEngine",
    # manager
    "AntiDetectManager",
    "PlaywrightAntiDetectAdapter",
]
