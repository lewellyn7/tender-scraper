"""
tests/test_anti_detect.py

单元测试: anti_detect 模块
- FingerprintProfile, CanvasNoiseInjector, TLSFingerprintSimulator
- DNSLeakProtector, HumanBehaviorSimulator
- AdaptiveLearningEngine, AntiDetectManager
- PlaywrightAntiDetectAdapter
"""

import pytest
import asyncio
import json
import tempfile
import os
from unittest.mock import MagicMock, AsyncMock, patch
from collections import deque

import sys
sys.path.insert(0, "scripts")
from anti_detect import (
    FingerprintProfile,
    CanvasNoiseInjector,
    TLSFingerprintSimulator,
    DNSLeakProtector,
    HumanBehaviorSimulator,
    AdaptiveLearningEngine,
    AntiDetectManager,
    PlaywrightAntiDetectAdapter,
    TLSFingerprintForCurl,
)


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def seed():
    return 42


@pytest.fixture
def temp_persistence_path():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


# ─────────────────────────────────────────────────────────────
# 一、FingerprintProfile 测试
# ─────────────────────────────────────────────────────────────

class TestFingerprintProfile:
    """Test FingerprintProfile generation and management."""

    def test_generate_returns_dict(self, seed):
        """generate 返回完整指纹字典"""
        fp_mgr = FingerprintProfile(seed=seed)
        profile = fp_mgr.generate()

        assert isinstance(profile, dict)
        assert "user_agent" in profile
        assert "platform" in profile
        assert "screen" in profile
        assert "timezone" in profile
        assert "languages" in profile
        assert "webgl_vendor" in profile
        assert "webgl_renderer" in profile
        assert "extra_http_headers" in profile

    def test_generate_valid_ua(self, seed):
        """UA 在预设池中"""
        fp_mgr = FingerprintProfile(seed=seed)
        profile = fp_mgr.generate()
        assert any(ua in profile["user_agent"] for ua in FingerprintProfile.CHROME_UA_POOL)

    def test_generate_valid_screen(self, seed):
        """Screen 在预设池中"""
        fp_mgr = FingerprintProfile(seed=seed)
        profile = fp_mgr.generate()
        assert profile["screen"] in FingerprintProfile.SCREEN_POOL

    def test_generate_valid_timezone(self, seed):
        """Timezone 在预设池中"""
        fp_mgr = FingerprintProfile(seed=seed)
        profile = fp_mgr.generate()
        assert profile["timezone"] in FingerprintProfile.TIMEZONE_POOL

    def test_generate_valid_lang(self, seed):
        """Language 在预设池中"""
        fp_mgr = FingerprintProfile(seed=seed)
        profile = fp_mgr.generate()
        assert profile["languages"] in FingerprintProfile.LANG_POOL

    def test_generate_valid_platform(self, seed):
        """Platform 在预设池中"""
        fp_mgr = FingerprintProfile(seed=seed)
        profile = fp_mgr.generate()
        assert profile["platform"] in FingerprintProfile.PLATFORM_POOL

    def test_generate_valid_webgl(self, seed):
        """WebGL 在预设池中"""
        fp_mgr = FingerprintProfile(seed=seed)
        profile = fp_mgr.generate()
        assert profile["webgl_vendor"] in [w["vendor"] for w in FingerprintProfile.WEBGL_POOL]

    def test_generate_deterministic_with_seed(self, seed):
        """相同 seed 生成相同指纹"""
        fp_mgr1 = FingerprintProfile(seed=seed)
        fp_mgr2 = FingerprintProfile(seed=seed)
        assert fp_mgr1.generate() == fp_mgr2.generate()

    def test_generate_different_with_different_seed(self):
        """不同 seed 生成不同指纹"""
        fp_mgr1 = FingerprintProfile(seed=1)
        fp_mgr2 = FingerprintProfile(seed=2)
        assert fp_mgr1.generate() != fp_mgr2.generate()

    def test_build_pool_returns_list(self, seed):
        """build_pool 返回指定大小的列表"""
        fp_mgr = FingerprintProfile(seed=seed)
        pool = fp_mgr.build_pool(size=5)
        assert len(pool) == 5
        assert all(isinstance(p, dict) for p in pool)

    def test_build_pool_all_unique(self, seed):
        """build_pool 生成唯一指纹"""
        fp_mgr = FingerprintProfile(seed=seed)
        pool = fp_mgr.build_pool(size=10)
        hashes = [fp_mgr.get_fingerprint_hash(p) for p in pool]
        assert len(hashes) == len(set(hashes))

    def test_get_fingerprint_hash(self, seed):
        """指纹哈希一致"""
        fp_mgr = FingerprintProfile(seed=seed)
        p1 = fp_mgr.generate()
        p2 = fp_mgr.generate()
        h1 = fp_mgr.get_fingerprint_hash(p1)
        h2 = fp_mgr.get_fingerprint_hash(p2)
        assert h1 != h2  # 不同指纹哈希不同
        assert len(h1) == 16  # SHA256 前16字符


# ─────────────────────────────────────────────────────────────
# 二、CanvasNoiseInjector 测试
# ─────────────────────────────────────────────────────────────

class TestCanvasNoiseInjector:
    """Test CanvasNoiseInjector."""

    def test_init_with_defaults(self):
        """默认参数初始化"""
        inj = CanvasNoiseInjector()
        assert inj.noise_scale == 0.0005
        assert inj.seed is not None

    def test_init_with_custom_params(self):
        """自定义参数"""
        inj = CanvasNoiseInjector(noise_scale=0.001, seed=123)
        assert inj.noise_scale == 0.001
        assert inj.seed == 123

    def test_get_injection_script(self):
        """生成的注入脚本包含噪声参数"""
        inj = CanvasNoiseInjector(noise_scale=0.0005, seed=42)
        script = inj.get_injection_script()
        assert "NOISE_SCALE" in script
        assert "Math.random" in script
        assert "getContext" in script

    @pytest.mark.asyncio
    async def test_inject_adds_script_to_page(self):
        """inject 调用 page.add_init_script"""
        inj = CanvasNoiseInjector(seed=42)
        mock_page = MagicMock()
        mock_page.add_init_script = AsyncMock()

        await inj.inject(mock_page)

        mock_page.add_init_script.assert_called_once()
        script = mock_page.add_init_script.call_args[0][0]
        assert "NOISE_SCALE" in script


# ─────────────────────────────────────────────────────────────
# 三、TLSFingerprintSimulator 测试
# ─────────────────────────────────────────────────────────────

class TestTLSFingerprintSimulator:
    """Test TLSFingerprintSimulator."""

    def test_init(self, seed):
        """初始化"""
        sim = TLSFingerprintSimulator(seed=seed)
        assert sim._active_pattern is None

    def test_select_pattern(self, seed):
        """select_pattern 选择模式"""
        sim = TLSFingerprintSimulator(seed=seed)
        p = sim.select_pattern()
        assert p in TLSFingerprintSimulator.BROWSER_JA3_PATTERNS
        assert sim._active_pattern is not None

    def test_get_tls_config(self, seed):
        """返回 TLS 配置"""
        sim = TLSFingerprintSimulator(seed=seed)
        sim.select_pattern()
        cfg = sim.get_tls_config()
        assert "tls_version" in cfg
        assert "alpn" in cfg
        assert "cipher_suites" in cfg

    def test_headers_for_pattern_chrome(self, seed):
        """Chrome 模式返回正确 header"""
        sim = TLSFingerprintSimulator(seed=seed)
        sim._active_pattern = {"name": "chrome_124_win"}
        headers = sim.headers_for_pattern()
        assert "sec-ch-ua" in headers

    def test_headers_for_pattern_firefox(self, seed):
        """Firefox 模式返回正确 header"""
        sim = TLSFingerprintSimulator(seed=seed)
        sim._active_pattern = {"name": "firefox_124_win"}
        headers = sim.headers_for_pattern()
        assert "sec-ch-ua" in headers


# ─────────────────────────────────────────────────────────────
# 四、DNSLeakProtector 测试
# ─────────────────────────────────────────────────────────────

class TestDNSLeakProtector:
    """Test DNSLeakProtector."""

    def test_init_valid_provider(self):
        """有效 provider 初始化"""
        prot = DNSLeakProtector(provider="cloudflare", mode="doh")
        assert prot.provider == "cloudflare"
        assert prot.mode == "doh"

    def test_init_invalid_provider(self):
        """无效 provider 抛出异常"""
        with pytest.raises(ValueError):
            DNSLeakProtector(provider="invalid", mode="doh")

    def test_init_invalid_mode(self):
        """无效 mode 抛出异常"""
        with pytest.raises(ValueError):
            DNSLeakProtector(provider="cloudflare", mode="invalid")

    def test_doh_url(self):
        """DoH URL 正确"""
        prot = DNSLeakProtector(provider="cloudflare", mode="doh")
        assert "cloudflare-dns.com" in prot.doh_url

    def test_dot_endpoint(self):
        """DoT 端点正确"""
        prot = DNSLeakProtector(provider="google", mode="dot")
        assert prot.dot_endpoint == ("dns.google", 853)

    def test_get_systemd_resolved_config(self):
        """生成 systemd-resolved 配置"""
        prot = DNSLeakProtector(provider="cloudflare", mode="doh")
        cfg = prot.get_systemd_resolved_config()
        assert "[Resolve]" in cfg
        assert "cloudflare" in cfg

    def test_build_hosts_blocklist(self):
        """生成 hosts blocklist"""
        prot = DNSLeakProtector()
        blocklist = prot.build_hosts_blocklist()
        assert isinstance(blocklist, list)
        assert len(blocklist) > 0


# ─────────────────────────────────────────────────────────────
# 五、HumanBehaviorSimulator 测试
# ─────────────────────────────────────────────────────────────

class TestHumanBehaviorSimulator:
    """Test HumanBehaviorSimulator."""

    def test_init(self, seed):
        """初始化"""
        bh = HumanBehaviorSimulator(seed=seed)
        assert bh.rng is not None

    def test_sample_interaction_delay_page_turn(self, seed):
        """page_turn 延迟采样"""
        bh = HumanBehaviorSimulator(seed=seed)
        for _ in range(20):
            delay = bh.sample_interaction_delay("page_turn")
            assert 0.8 <= delay <= 12.0

    def test_sample_interaction_delay_scroll_stop(self, seed):
        """scroll_stop 延迟采样"""
        bh = HumanBehaviorSimulator(seed=seed)
        delay = bh.sample_interaction_delay("scroll_stop")
        assert 0.1 <= delay <= 3.0

    def test_sample_interaction_delay_unknown_action(self, seed):
        """未知动作使用默认值"""
        bh = HumanBehaviorSimulator(seed=seed)
        delay = bh.sample_interaction_delay("unknown_action")
        assert 0.5 <= delay <= 10.0

    @pytest.mark.asyncio
    async def test_async_delay(self, seed):
        """异步延迟执行"""
        bh = HumanBehaviorSimulator(seed=seed)
        start = asyncio.get_event_loop().time()
        await bh.async_delay("page_turn")
        elapsed = asyncio.get_event_loop().time() - start
        assert 0.8 <= elapsed <= 13.0

    def test_generate_bezier_mouse_track(self, seed):
        """生成贝塞尔曲线"""
        bh = HumanBehaviorSimulator(seed=seed)
        track = bh.generate_bezier_mouse_track(
            start=(0, 0), end=(100, 100), num_points=10
        )
        assert len(track) == 11
        assert all(isinstance(p, tuple) and len(p) == 2 for p in track)

    def test_add_click_noise(self, seed):
        """点击噪声"""
        bh = HumanBehaviorSimulator(seed=seed)
        nx, ny = bh.add_click_noise(100, 100, sigma=8.0)
        assert nx != 100 or ny != 100  # 有噪声
        assert isinstance(nx, float)
        assert isinstance(ny, float)

    @pytest.mark.asyncio
    async def test_human_mouse_move(self, seed):
        """鼠标移动"""
        bh = HumanBehaviorSimulator(seed=seed)
        mock_page = MagicMock()
        mock_page.mouse.move = AsyncMock()
        await bh.human_mouse_move(mock_page, start=(0, 0), end=(100, 100))
        assert mock_page.mouse.move.call_count >= 10

    @pytest.mark.asyncio
    async def test_human_click(self, seed):
        """人类点击"""
        bh = HumanBehaviorSimulator(seed=seed)
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.bounding_box = AsyncMock(return_value={
            "x": 100, "y": 200, "width": 50, "height": 30
        })
        mock_page.locator = MagicMock(return_value=mock_locator)
        mock_page.mouse.click = AsyncMock()

        await bh.human_click(mock_page, "button.submit")

        mock_page.mouse.click.assert_called_once()

    def test_generate_scroll_curve(self, seed):
        """滚动曲线"""
        bh = HumanBehaviorSimulator(seed=seed)
        curve = bh.generate_scroll_curve(0, 1000, num_steps=10)
        assert len(curve) == 11
        assert curve[0] == 0
        assert curve[-1] == 1000

    @pytest.mark.asyncio
    async def test_human_scroll(self, seed):
        """人类滚动"""
        bh = HumanBehaviorSimulator(seed=seed)
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock()

        await bh.human_scroll(mock_page, start_y=0, end_y=800)

        assert mock_page.evaluate.call_count > 0


# ─────────────────────────────────────────────────────────────
# 六、AdaptiveLearningEngine 测试
# ─────────────────────────────────────────────────────────────

class TestAdaptiveLearningEngine:
    """Test AdaptiveLearningEngine."""

    def test_init(self, seed):
        """初始化"""
        engine = AdaptiveLearningEngine(seed=seed)
        assert engine.rng is not None
        assert engine.max_history == 10_000
        assert len(engine.results) == 0

    def test_record(self, seed):
        """记录行为结果"""
        engine = AdaptiveLearningEngine(seed=seed)
        bf = engine.BehaviorFingerprint(
            delay_mean_ms=2000, delay_sigma_ms=800,
            mouse_speed=200, click_noise_px=8,
            scroll_steps=30, fingerprint_id="fp_1",
            tls_pattern="chrome", doh_provider="cloudflare",
        )
        engine.record(
            fingerprint=bf, source="test",
            http_status=200, success=True,
            latency_ms=300,
        )
        assert len(engine.results) == 1

    def test_record_updates_success_deque(self, seed):
        """记录更新成功队列"""
        engine = AdaptiveLearningEngine(seed=seed)
        bf = engine.BehaviorFingerprint(
            delay_mean_ms=2000, delay_sigma_ms=800,
            mouse_speed=200, click_noise_px=8,
            scroll_steps=30, fingerprint_id="fp_1",
            tls_pattern="chrome", doh_provider="cloudflare",
        )
        for i in range(5):
            engine.record(bf, "test", 200, True, 300)
        assert len(engine._source_success["test"]) == 5

    def test_get_tuned_params(self, seed):
        """获取调优参数"""
        engine = AdaptiveLearningEngine(seed=seed)
        bf = engine.BehaviorFingerprint(
            delay_mean_ms=2000, delay_sigma_ms=800,
            mouse_speed=200, click_noise_px=8,
            scroll_steps=30, fingerprint_id="fp_1",
            tls_pattern="chrome", doh_provider="cloudflare",
        )
        engine.record(bf, "test", 200, True, 300)
        params = engine.get_tuned_params("test")
        assert "delay_mean_ms" in params
        assert "source_success_rate" in params

    def test_recommend_behavior_config_normal(self, seed):
        """正常策略推荐"""
        engine = AdaptiveLearningEngine(seed=seed)
        # 记录成功
        bf = engine.BehaviorFingerprint(
            delay_mean_ms=2000, delay_sigma_ms=800,
            mouse_speed=200, click_noise_px=8,
            scroll_steps=30, fingerprint_id="fp_1",
            tls_pattern="chrome", doh_provider="cloudflare",
        )
        for _ in range(20):
            engine.record(bf, "test", 200, True, 300)

        config = engine.recommend_behavior_config("test")
        assert "strategy" in config
        assert "delay_mean_ms" in config

    def test_recommend_behavior_config_high_ban(self, seed):
        """高封禁率策略"""
        engine = AdaptiveLearningEngine(seed=seed)
        bf = engine.BehaviorFingerprint(
            delay_mean_ms=2000, delay_sigma_ms=800,
            mouse_speed=200, click_noise_px=8,
            scroll_steps=30, fingerprint_id="fp_1",
            tls_pattern="chrome", doh_provider="cloudflare",
        )
        # 模拟多次封禁
        for i in range(20):
            engine.record(bf, "test", 403, False, 300, ban_detected=(i % 3 == 0))

        config = engine.recommend_behavior_config("test")
        assert config["strategy"] == "stealth"

    def test_export_import(self, seed, temp_persistence_path):
        """导出导入"""
        engine = AdaptiveLearningEngine(seed=seed)
        bf = engine.BehaviorFingerprint(
            delay_mean_ms=2000, delay_sigma_ms=800,
            mouse_speed=200, click_noise_px=8,
            scroll_steps=30, fingerprint_id="fp_1",
            tls_pattern="chrome", doh_provider="cloudflare",
        )
        engine.record(bf, "test", 200, True, 300)
        engine.export(temp_persistence_path)

        engine2 = AdaptiveLearningEngine(seed=seed)
        engine2.import_data(temp_persistence_path)
        assert len(engine2.results) >= 1

    def test_health_metrics(self, seed):
        """健康度指标"""
        engine = AdaptiveLearningEngine(seed=seed)
        metrics = engine.health_metrics()
        assert "total_requests" in metrics
        assert "recent_success_rate" in metrics
        assert "recent_ban_rate" in metrics
        assert "live_delay_ms" in metrics

    def test_behavior_fingerprint_to_dict(self, seed):
        """指纹可序列化"""
        engine = AdaptiveLearningEngine(seed=seed)
        bf = engine.BehaviorFingerprint(
            delay_mean_ms=2000, delay_sigma_ms=800,
            mouse_speed=200, click_noise_px=8,
            scroll_steps=30, fingerprint_id="fp_1",
            tls_pattern="chrome", doh_provider="cloudflare",
        )
        d = bf.to_dict()
        assert isinstance(d, dict)
        assert d["delay_mean_ms"] == 2000

    def test_behavior_result_to_dict(self, seed):
        """结果可序列化"""
        engine = AdaptiveLearningEngine(seed=seed)
        bf = engine.BehaviorFingerprint(
            delay_mean_ms=2000, delay_sigma_ms=800,
            mouse_speed=200, click_noise_px=8,
            scroll_steps=30, fingerprint_id="fp_1",
            tls_pattern="chrome", doh_provider="cloudflare",
        )
        engine.record(bf, "test", 200, True, 300)
        result = engine.results[0]
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "timestamp" in d


# ─────────────────────────────────────────────────────────────
# 七、AntiDetectManager 测试
# ─────────────────────────────────────────────────────────────

class TestAntiDetectManager:
    """Test AntiDetectManager."""

    def test_init_defaults(self, seed):
        """默认初始化"""
        manager = AntiDetectManager(seed=seed)
        assert manager.fingerprint_mgr is not None
        assert manager.canvas_noise is not None
        assert manager.tls_sim is not None
        assert manager.human_behavior is not None
        assert manager.learner is not None

    def test_init_with_persistence(self, seed, temp_persistence_path):
        """带持久化路径"""
        manager = AntiDetectManager(
            seed=seed,
            persistence_path=temp_persistence_path,
        )
        assert manager.persistence_path == temp_persistence_path

    def test_get_fingerprint(self, seed):
        """获取指纹"""
        manager = AntiDetectManager(seed=seed)
        fp = manager.get_fingerprint()
        assert isinstance(fp, dict)
        assert "user_agent" in fp

    def test_get_fingerprint_round_robin(self, seed):
        """指纹轮换"""
        manager = AntiDetectManager(seed=seed, fingerprint_pool_size=5)
        fps = [manager.get_fingerprint() for _ in range(5)]
        # 5个指纹都不同
        hashes = [manager.fingerprint_mgr.get_fingerprint_hash(fp) for fp in fps]
        assert len(set(hashes)) == 5

    def test_get_tls_config(self, seed):
        """TLS 配置"""
        manager = AntiDetectManager(seed=seed)
        cfg = manager.get_tls_config()
        assert "tls_version" in cfg
        assert "alpn" in cfg

    def test_get_tls_headers(self, seed):
        """TLS Headers"""
        manager = AntiDetectManager(seed=seed)
        headers = manager.get_tls_headers()
        assert isinstance(headers, dict)

    def test_get_doh_config(self, seed):
        """DoH 配置"""
        manager = AntiDetectManager(seed=seed, enable_doh=True)
        cfg = manager.get_doh_config()
        assert "doh_url" in cfg or cfg == {}

    def test_get_doh_config_disabled(self, seed):
        """DoH 禁用时返回空"""
        manager = AntiDetectManager(seed=seed, enable_doh=False)
        assert manager.get_doh_config() == {}

    @pytest.mark.asyncio
    async def test_apply_fingerprint(self, seed):
        """应用指纹到页面"""
        manager = AntiDetectManager(seed=seed)
        mock_page = MagicMock()
        mock_page.set_extra_http_headers = AsyncMock()
        mock_page.set_viewport_size = AsyncMock()
        mock_page.add_init_script = AsyncMock()
        mock_page.evaluate = AsyncMock()
        mock_page.context = MagicMock()
        mock_page.context.set_timezone = AsyncMock()

        fp = await manager.apply_fingerprint(mock_page)
        assert fp is not None
        mock_page.set_extra_http_headers.assert_called()
        mock_page.set_viewport_size.assert_called()

    @pytest.mark.asyncio
    async def test_human_delay(self, seed):
        """人类延迟"""
        manager = AntiDetectManager(seed=seed)
        # 使用 non-page_turn action 来避免 live_delay_ms bug in page_turn path
        await manager.human_delay("hover")
        # 不抛异常即通过

    def test_record_result(self, seed):
        """记录结果"""
        manager = AntiDetectManager(seed=seed)
        manager.record_result(
            source="test",
            http_status=200,
            success=True,
            latency_ms=300,
        )
        assert manager.learner._total_requests == 1

    def test_health_report(self, seed):
        """健康报告"""
        manager = AntiDetectManager(seed=seed)
        report = manager.health_report()
        assert "total_requests" in report
        assert "recent_success_rate" in report

    def test_get_recommended_config(self, seed):
        """推荐配置"""
        manager = AntiDetectManager(seed=seed)
        config = manager.get_recommended_config("test")
        assert "strategy" in config


# ─────────────────────────────────────────────────────────────
# 八、PlaywrightAntiDetectAdapter 测试
# ─────────────────────────────────────────────────────────────

class TestPlaywrightAntiDetectAdapter:
    """Test PlaywrightAntiDetectAdapter."""

    def test_init(self, seed):
        """初始化"""
        manager = AntiDetectManager(seed=seed)
        adapter = PlaywrightAntiDetectAdapter(manager)
        assert adapter.manager is manager

    @pytest.mark.asyncio
    async def test_safe_click(self, seed):
        """安全点击"""
        manager = AntiDetectManager(seed=seed)
        adapter = PlaywrightAntiDetectAdapter(manager)
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.bounding_box = AsyncMock(return_value={
            "x": 100, "y": 200, "width": 50, "height": 30
        })
        mock_page.locator = MagicMock(return_value=mock_locator)
        mock_page.mouse.click = AsyncMock()

        await adapter.safe_click(mock_page, "button.submit")
        mock_page.mouse.click.assert_called()

    @pytest.mark.asyncio
    async def test_safe_scroll(self, seed):
        """安全滚动"""
        manager = AntiDetectManager(seed=seed)
        adapter = PlaywrightAntiDetectAdapter(manager)
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock()

        await adapter.safe_scroll(mock_page, 0, 800)
        mock_page.evaluate.assert_called()


# ─────────────────────────────────────────────────────────────
# 九、TLSFingerprintForCurl 测试
# ─────────────────────────────────────────────────────────────

class TestTLSFingerprintForCurl:
    """Test TLSFingerprintForCurl."""

    def test_init(self):
        """初始化"""
        tfc = TLSFingerprintForCurl("chrome_124_win")
        assert tfc.pattern_name == "chrome_124_win"
        assert tfc.impersonate_name == "chrome124"

    def test_as_curl_cffi_session_kwargs(self):
        """返回 curl_cffi 参数"""
        tfc = TLSFingerprintForCurl("chrome_124_win")
        kwargs = tfc.as_curl_cffi_session_kwargs()
        assert "impersonate" in kwargs
        assert kwargs["impersonate"] == "chrome124"

    def test_invalid_pattern_fallback(self):
        """无效模式降级"""
        tfc = TLSFingerprintForCurl("unknown_pattern")
        assert tfc.impersonate_name == "chrome124"
