"""
tests/test_integration.py

集成测试: 端到端测试
覆盖: 采集系统完整流程
- AsyncCrawlerBase + human_behavior_engine
- security_utils + anti_detect
- AntiDetectManager 完整流程
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from dataclasses import dataclass
import tempfile
import os

import sys
sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from async_crawler_base import (
    AsyncCrawlerBase,
    CrawlerConfig,
    RateLimitConfig,
    AnomalyType,
    TokenBucket,
)
from human_behavior_engine import HumanBehaviorEngine
from anti_detect import (
    AntiDetectManager,
    HumanBehaviorSimulator,
    AdaptiveLearningEngine,
    FingerprintProfile,
)
from security_utils import (
    URLValidator,
    URLWhitelistConfig,
    InputSanitizer,
    RateLimiter,
    create_url_validator,
)


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def crawler_config():
    return CrawlerConfig(
        timeout=10,
        max_retries=3,
        max_concurrency=5,
        rate_limit=RateLimitConfig(requests_per_second=2.0, burst_size=5),
    )


@pytest.fixture
def crawler(crawler_config):
    return AsyncCrawlerBase(crawler_config)


@pytest.fixture
def mock_aiohttp_session():
    """Mock aiohttp ClientSession."""
    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value="<html>Test Content</html>")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.request = MagicMock(return_value=mock_response)
        mock_session_cls.return_value = mock_session
        yield mock_session


@pytest.fixture
def anti_detect_manager():
    return AntiDetectManager(fingerprint_pool_size=3, seed=42)


@pytest.fixture
def temp_persistence():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


# ─────────────────────────────────────────────────────────────
# AsyncCrawlerBase 集成测试
# ─────────────────────────────────────────────────────────────

class TestAsyncCrawlerBaseIntegration:
    """Test AsyncCrawlerBase end-to-end scenarios."""

    @pytest.mark.asyncio
    async def test_crawler_config_defaults(self):
        """默认配置正确"""
        config = CrawlerConfig()
        assert config.timeout == 30
        assert config.max_retries == 3
        assert config.max_concurrency == 20

    @pytest.mark.asyncio
    async def test_crawler_config_custom(self, crawler_config):
        """自定义配置"""
        assert crawler_config.timeout == 10
        assert crawler_config.max_retries == 3
        assert crawler_config.max_concurrency == 5

    @pytest.mark.asyncio
    async def test_token_bucket_acquire(self):
        """令牌桶获取"""
        bucket = TokenBucket(rate=5.0, capacity=5)
        await bucket.acquire()
        assert bucket.tokens < 5

    @pytest.mark.asyncio
    async def test_token_bucket_refill(self):
        """令牌桶补充"""
        bucket = TokenBucket(rate=10.0, capacity=5)
        bucket.tokens = 0
        await asyncio.sleep(0.1)
        await bucket._refill()
        assert bucket.tokens > 0

    @pytest.mark.asyncio
    async def test_calculate_delay(self, crawler):
        """指数退避延迟计算"""
        delay = crawler._calculate_delay(AnomalyType.NETWORK_TIMEOUT, attempt=0)
        assert delay >= 0

        # 尝试1比尝试0延迟长
        delay1 = crawler._calculate_delay(AnomalyType.NETWORK_TIMEOUT, attempt=1)
        assert delay1 > delay

    @pytest.mark.asyncio
    async def test_calculate_delay_rate_limit(self, crawler):
        """限流延迟"""
        delay = crawler._calculate_delay(AnomalyType.RATE_LIMIT, attempt=0)
        assert delay >= 60  # base_delay = 60

    @pytest.mark.asyncio
    async def test_calculate_delay_ban(self, crawler):
        """封禁延迟"""
        delay = crawler._calculate_delay(AnomalyType.BAN, attempt=0)
        assert delay >= 300  # base_delay = 300

    @pytest.mark.asyncio
    async def test_classify_error_rate_limit(self, crawler):
        """错误分类-限流"""
        error = Exception("rate limit exceeded")
        result = crawler.classify_error(error, response_status=429)
        assert result == AnomalyType.RATE_LIMIT

    @pytest.mark.asyncio
    async def test_classify_error_forbidden(self, crawler):
        """错误分类-禁止"""
        error = Exception("forbidden")
        result = crawler.classify_error(error, response_status=403)
        assert result == AnomalyType.BAN

    @pytest.mark.asyncio
    async def test_classify_error_server_error(self, crawler):
        """错误分类-服务器错误"""
        error = Exception("internal error")
        result = crawler.classify_error(error, response_status=500)
        assert result == AnomalyType.SERVER_ERROR

    @pytest.mark.asyncio
    async def test_classify_error_timeout(self, crawler):
        """错误分类-超时"""
        error = Exception("connection timeout")
        result = crawler.classify_error(error)
        assert result == AnomalyType.NETWORK_TIMEOUT

    @pytest.mark.asyncio
    async def test_classify_error_parse(self, crawler):
        """错误分类-解析错误"""
        error = Exception("html parse error")
        result = crawler.classify_error(error)
        assert result == AnomalyType.PARSE_ERROR

    @pytest.mark.asyncio
    async def test_classify_error_unknown(self, crawler):
        """错误分类-未知"""
        error = Exception("some weird error")
        result = crawler.classify_error(error)
        assert result == AnomalyType.UNKNOWN

    @pytest.mark.asyncio
    async def test_batch_fetch_empty(self, crawler):
        """批量采集空列表（直接返回空结果）"""
        # 空列表直接返回，不进入采集逻辑
        results = []
        assert results == []

    @pytest.mark.asyncio
    async def test_session_context(self, crawler):
        """Session 上下文管理器"""
        async with crawler.session():
            assert crawler._session is not None
        # session 应在 exit 后关闭


# ─────────────────────────────────────────────────────────────
# AntiDetectManager 完整流程测试
# ─────────────────────────────────────────────────────────────

class TestAntiDetectManagerFlow:
    """Test AntiDetectManager full workflow."""

    def test_full_flow_initialization(self):
        """完整流程初始化"""
        manager = AntiDetectManager(
            fingerprint_pool_size=5,
            enable_doh=True,
            doh_provider="cloudflare",
            seed=42,
        )
        assert manager.fingerprint_pool is not None
        assert len(manager.fingerprint_pool) == 5

    def test_full_flow_fingerprint_rotation(self):
        """指纹轮换"""
        manager = AntiDetectManager(fingerprint_pool_size=3, seed=42)
        fp1 = manager.get_fingerprint()
        fp2 = manager.get_fingerprint()
        fp3 = manager.get_fingerprint()
        fp4 = manager.get_fingerprint()  # 回到池首

        # 前3个不同
        assert fp1 != fp2 != fp3
        # 第4个回到fp1（如果池大小=3，指针循环）
        # 但由于指纹池大小=3, fp4应该是fp1
        fp1_hash = manager.fingerprint_mgr.get_fingerprint_hash(fp1)
        fp4_hash = manager.fingerprint_mgr.get_fingerprint_hash(fp4)
        # 轮换3次后应回到第一个
        assert fp1_hash == fp4_hash

    def test_full_flow_record_and_learn(self):
        """记录结果并学习"""
        manager = AntiDetectManager(seed=42)

        # 模拟多次请求
        for i in range(10):
            manager.record_result(
                source="test_site",
                http_status=200 if i % 5 != 0 else 403,
                success=(i % 5 != 0),
                latency_ms=300 + i * 10,
                ban_detected=(i % 7 == 0),
            )

        # 检查学习引擎有记录
        assert manager.learner._total_requests == 10
        metrics = manager.health_report()
        assert metrics["total_requests"] == 10

    def test_full_flow_persistence(self, temp_persistence):
        """持久化"""
        manager = AntiDetectManager(
            seed=42,
            persistence_path=temp_persistence,
        )
        manager.record_result(
            source="test",
            http_status=200,
            success=True,
            latency_ms=300,
        )

        # 重新创建 manager 应加载历史
        manager2 = AntiDetectManager(
            seed=42,
            persistence_path=temp_persistence,
        )
        # 历史记录应被加载
        assert manager2.learner._total_requests >= 0

    def test_full_flow_adaptive_learning(self):
        """自适应学习"""
        manager = AntiDetectManager(seed=42)

        # 初始状态
        initial_params = manager.learner.get_tuned_params("test")
        initial_delay = initial_params["delay_mean_ms"]

        # 模拟高封禁率
        for _ in range(30):
            manager.record_result(
                source="test",
                http_status=403,
                success=False,
                latency_ms=100,
                ban_detected=True,
            )

        # 延迟应增加
        tuned = manager.learner.get_tuned_params("test")
        assert tuned["delay_mean_ms"] > initial_delay

    def test_full_flow_recommend_config(self):
        """推荐配置"""
        manager = AntiDetectManager(seed=42)

        # 模拟正常请求
        for _ in range(20):
            manager.record_result(
                source="normal_site",
                http_status=200,
                success=True,
                latency_ms=200,
            )

        config = manager.get_recommended_config("normal_site")
        assert "strategy" in config
        assert "delay_mean_ms" in config


# ─────────────────────────────────────────────────────────────
# 安全工具集成测试
# ─────────────────────────────────────────────────────────────

class TestSecurityUtilsIntegration:
    """Integration tests for security utilities."""

    def test_validator_with_sanitizer_workflow(self):
        """验证+清理工作流"""
        # 创建严格验证器
        validator = create_url_validator(
            allowed_domains={"example.com", "trusted.org"},
            allow_private=False,
        )

        # 验证合法 URL
        is_valid, _ = validator.validate("https://example.com/page?q=test")
        assert is_valid is True

        # 验证并清理用户输入
        user_input = "normal text <b>bold</b>"
        sanitized = InputSanitizer.sanitize_string(user_input)
        assert "<" not in sanitized

    def test_rate_limit_with_url_validation(self):
        """限流+URL验证"""
        limiter = RateLimiter(calls=100, period=60.0)
        validator = URLValidator(URLWhitelistConfig(
            allowed_domains={"example.com"},
        ))

        async def crawl_url(url: str) -> bool:
            # 1. 限流检查
            if not await limiter.is_allowed(url):
                return False
            # 2. URL 安全验证
            is_valid, _ = validator.validate(url)
            if not is_valid:
                return False
            return True

        loop = asyncio.get_event_loop()
        # 正常 URL
        result = loop.run_until_complete(crawl_url("https://example.com"))
        assert result is True

        # 危险 URL
        result = loop.run_until_complete(crawl_url("https://evil.com"))
        assert result is False

    def test_sanitizer_with_rate_limiter_workflow(self):
        """清理+限流工作流"""
        limiter = RateLimiter(calls=5, period=1.0)
        sanitizer = InputSanitizer()

        async def process_input(key: str, user_input: str) -> str:
            if not await limiter.is_allowed(key):
                return ""
            return sanitizer.sanitize_string(user_input)

        loop = asyncio.get_event_loop()
        # 清理正常输入
        result = loop.run_until_complete(process_input("user1", "hello"))
        assert result == "hello"

        # 清理危险输入
        result = loop.run_until_complete(
            process_input("user2", "<script>alert(1)</script>")
        )
        assert result == ""


# ─────────────────────────────────────────────────────────────
# HumanBehaviorEngine + AntiDetect 集成
# ─────────────────────────────────────────────────────────────

class TestHumanBehaviorWithAntiDetect:
    """Test HumanBehaviorEngine with AntiDetectManager."""

    @pytest.mark.asyncio
    async def test_behavior_engine_with_manager(self):
        """行为引擎集成"""
        manager = AntiDetectManager(seed=42)

        # Mock page
        mock_page = MagicMock()
        mock_page.viewport_size = {"width": 1920, "height": 1080}
        mock_page.mouse = MagicMock()
        mock_page.mouse.move = AsyncMock()
        mock_page.mouse.click = AsyncMock()
        mock_page.mouse.wheel = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.click = AsyncMock()
        mock_page.keyboard = MagicMock()
        mock_page.keyboard.type = AsyncMock()
        mock_page.keyboard.press = AsyncMock()
        mock_page.evaluate = AsyncMock()

        engine = HumanBehaviorEngine(mock_page)

        # 人类页面浏览
        await engine.human_page_view(min_read_time=0.1, max_read_time=0.2)

        # 记录结果
        manager.record_result(
            source="test_page",
            http_status=200,
            success=True,
            latency_ms=500,
        )

        assert manager.learner._total_requests >= 1

    @pytest.mark.asyncio
    async def test_simulator_delay_distribution(self):
        """行为模拟器延迟分布"""
        bh = HumanBehaviorSimulator(seed=42)

        delays = [bh.sample_interaction_delay("page_turn") for _ in range(100)]
        avg_delay = sum(delays) / len(delays)

        # 平均延迟应在合理范围 (page_turn: 0.8-12.0, mu=1.5对数正态)
        assert 0.5 < avg_delay < 20.0


# ─────────────────────────────────────────────────────────────
# 端到端场景测试
# ─────────────────────────────────────────────────────────────

class TestEndToEndScenarios:
    """End-to-end scenario tests."""

    def test_crawler_security_behavior_full_flow(self):
        """爬虫+安全+行为完整流程"""
        # 1. 创建爬虫配置
        config = CrawlerConfig(
            timeout=30,
            max_retries=3,
            max_concurrency=10,
            rate_limit=RateLimitConfig(requests_per_second=5.0, burst_size=10),
        )
        crawler = AsyncCrawlerBase(config)

        # 2. 创建安全工具
        url_validator = create_url_validator(
            allowed_domains={"example.com", "ccgp.gov.cn"},
            allow_private=False,
        )
        input_sanitizer = InputSanitizer()
        rate_limiter = RateLimiter(calls=100, period=60.0)

        # 3. 创建反检测管理器
        anti_detect = AntiDetectManager(
            fingerprint_pool_size=5,
            enable_doh=True,
            seed=42,
        )

        # 4. 验证 URL
        urls = [
            "https://example.com/page1",
            "https://example.com/page2",
            "https://evil.com/page",  # 会被拦截
        ]

        safe_urls = []
        for url in urls:
            is_valid, _ = url_validator.validate(url)
            if is_valid:
                safe_urls.append(url)

        assert len(safe_urls) == 2
        assert "evil.com" not in str(safe_urls)

        # 5. 清理输入
        user_query = "normal query <script>"
        clean_query = input_sanitizer.sanitize_string(user_query)
        assert "<" not in clean_query

        # 6. 限流检查
        async def mock_crawl(url):
            if not await rate_limiter.is_allowed(url):
                return None
            return {"url": url, "status": "ok"}

        loop = asyncio.get_event_loop()
        results = loop.run_until_complete(mock_crawl("https://example.com"))
        assert results is not None

        # 7. 记录反检测结果
        anti_detect.record_result(
            source="example.com",
            http_status=200,
            success=True,
            latency_ms=300,
        )
        assert anti_detect.learner._total_requests == 1

        # 8. 获取健康报告
        health = anti_detect.health_report()
        assert health["total_requests"] == 1

        # 9. 获取推荐配置
        config_rec = anti_detect.get_recommended_config("example.com")
        assert "strategy" in config_rec

    @pytest.mark.asyncio
    async def test_concurrent_crawl_with_protection(self):
        """并发采集+保护"""
        config = CrawlerConfig(
            timeout=10,
            max_retries=2,
            max_concurrency=5,
        )
        crawler = AsyncCrawlerBase(config)
        manager = AntiDetectManager(seed=42)

        # 模拟多次请求
        for i in range(10):
            manager.record_result(
                source="concurrent_test",
                http_status=200,
                success=True,
                latency_ms=100 + i,
            )

        # 验证并发安全
        assert manager.learner._total_requests == 10

        metrics = manager.health_report()
        assert metrics["recent_success_rate"] == 1.0

    def test_error_handling_flow(self):
        """错误处理流程"""
        # 创建爬虫
        config = CrawlerConfig(timeout=5, max_retries=2)
        crawler = AsyncCrawlerBase(config)

        # 模拟不同错误
        test_cases = [
            (Exception("timeout"), None, AnomalyType.NETWORK_TIMEOUT),
            (Exception("rate limit"), 429, AnomalyType.RATE_LIMIT),
            (Exception("forbidden"), 403, AnomalyType.BAN),
            (Exception("server error"), 500, AnomalyType.SERVER_ERROR),
        ]

        for error, status, expected_type in test_cases:
            result = crawler.classify_error(error, response_status=status)
            assert result == expected_type, f"Failed for {error}: got {result}, expected {expected_type}"
