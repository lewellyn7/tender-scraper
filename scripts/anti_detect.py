"""anti_detect shim - re-exports from app.core.harvest.anti_detect"""
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

__all__ = [
    "FingerprintProfile",
    "CanvasNoiseInjector",
    "TLSFingerprintSimulator",
    "TLSFingerprintForCurl",
    "DNSLeakProtector",
    "HumanBehaviorSimulator",
    "AdaptiveLearningEngine",
    "AntiDetectManager",
    "PlaywrightAntiDetectAdapter",
]
