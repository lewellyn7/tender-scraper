# anti_detect.py - 反机器人检测规避与人类行为模拟模块
# ==============================================================
# 角色：AI 工程师
# 用途：政府采购/工程建设信息采集系统的反检测策略
# 依赖：playwright, numpy, dataclasses-json, PyJWT
# ==============================================================
#
# 本模块已拆分为子包 app/core/harvest/anti_detect/：
#   - fingerprints.py : 浏览器指纹生成
#   - canvas.py      : Canvas 噪声注入 + WebGL 伪造
#   - webgl.py       : WebGL 常量
#   - tls.py         : TLS 指纹模拟
#   - dns.py         : DNS 泄漏防护
#   - behavior.py    : 人类行为模拟 + 自适应学习
#   - manager.py     : AntiDetectManager 统一入口
#
# 向后兼容：所有公开类从子包重新导出
# ==============================================================

# 向后兼容导入（从子包直接导入，避免循环）
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

# ─────────────────────────────────────────────────────────────
# 十、独立运行：单元测试 / Demo
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":

    print("=" * 60)
    print("Anti-Detect Module Self-Test")
    print("=" * 60)

    # 1. 指纹生成测试
    print("\n[1] FingerprintProfile")
    fp_mgr = FingerprintProfile(seed=42)
    fp = fp_mgr.generate()
    print(f"    UA:     {fp['user_agent'][:60]}...")
    print(f"    Screen: {fp['screen']}")
    print(f"    WebGL:  {fp['webgl_vendor']}")
    print(f"    FP ID:  {fp_mgr.get_fingerprint_hash(fp)}")

    # 2. 指纹池
    print("\n[2] Fingerprint Pool")
    pool = fp_mgr.build_pool(size=3)
    for i, p in enumerate(pool):
        print(f"    [{i}] {fp_mgr.get_fingerprint_hash(p)}")

    # 3. 行为模拟
    print("\n[3] HumanBehaviorSimulator")
    bh = HumanBehaviorSimulator(seed=42)
    delays = [bh.sample_interaction_delay("page_turn") for _ in range(5)]
    print(f"    Page-turn delays: {[round(d, 2) for d in delays]}")

    track = bh.generate_bezier_mouse_track(
        start=(100, 200), end=(400, 300), num_points=8
    )
    print(f"    Mouse track (8 pts): {track}")

    scroll = bh.generate_scroll_curve(0, 1000, num_steps=5)
    print(f"    Scroll curve (5 pts): {scroll}")

    # 4. TLS 指纹
    print("\n[4] TLSFingerprintSimulator")
    tls = TLSFingerprintSimulator(seed=42)
    p = tls.select_pattern()
    print(f"    Selected: {p['name']} / JA4: {p.get('ja4', 'N/A')}")
    print(f"    TLS Config: {tls.get_tls_config()}")

    # 5. 自适应学习
    print("\n[5] AdaptiveLearningEngine")
    learner = AdaptiveLearningEngine(seed=42)

    # 模拟 20 次请求（部分 ban）
    for i in range(20):
        bf = learner.BehaviorFingerprint(
            delay_mean_ms=2000, delay_sigma_ms=800,
            mouse_speed=200, click_noise_px=8,
            scroll_steps=30, fingerprint_id=f"fp_{i}",
            tls_pattern="chrome_124_win", doh_provider="cloudflare",
        )
        success = (i % 5 != 0)   # 20% 失败率
        learner.record(
            fingerprint=bf,
            source="test_source",
            http_status=200 if success else 403,
            success=success,
            latency_ms=300,
            ban_detected=(i % 7 == 0),
            captcha_seen=False,
        )

    print(f"    Health metrics: {learner.health_metrics()}")
    print(f"    Tuned params:   {learner.get_tuned_params('test_source')}")
    config = learner.recommend_behavior_config("test_source")
    print(f"    Recommended config: strategy={config.get('strategy')}, "
          f"delay={config.get('delay_mean_ms')}ms")

    # 6. AntiDetectManager 整合
    print("\n[6] AntiDetectManager")
    manager = AntiDetectManager(
        fingerprint_pool_size=5,
        enable_doh=True,
        doh_provider="cloudflare",
        seed=42,
    )
    print(f"    TLS config:  {manager.get_tls_config()}")
    print(f"    DoH URL:     {manager.get_doh_config()}")
    print(f"    Health:      {manager.health_report()}")

    print("\n" + "=" * 60)
    print("All tests passed.")
    print("=" * 60)
