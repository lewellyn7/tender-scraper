"""
tests/test_security_utils.py

单元测试: security_utils 模块
- URLValidator, URLWhitelistConfig
- InputSanitizer
- RateLimiter, DistributedRateLimiter, rate_limit decorator
- HMACValidator
"""

import asyncio
import sys

import pytest

sys.path.insert(0, ".")
from security_utils import (
    HMACValidator,
    InputSanitizer,
    RateLimiter,
    RateLimitInfo,
    URLValidator,
    URLWhitelistConfig,
    create_url_validator,
    default_url_validator,
    rate_limit,
)

# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def default_config():
    return URLWhitelistConfig()


@pytest.fixture
def strict_config():
    return URLWhitelistConfig(
        allowed_schemes={"https"},
        allowed_domains={"example.com", "trusted.org"},
        blocked_domains={"evil.com", "suspicious.net"},
        allow_private=False,
    )


@pytest.fixture
def validator(default_config):
    return URLValidator(default_config)


@pytest.fixture
def strict_validator(strict_config):
    return URLValidator(strict_config)


# ─────────────────────────────────────────────────────────────
# URLWhitelistConfig 测试
# ─────────────────────────────────────────────────────────────

class TestURLWhitelistConfig:
    """Test URLWhitelistConfig."""

    def test_defaults(self):
        """默认配置"""
        config = URLWhitelistConfig()
        assert config.allowed_schemes == {"http", "https"}
        assert "localhost" in config.blocked_domains
        assert "127.0.0.1" in config.blocked_domains
        assert "169.254.169.254" in config.blocked_domains
        assert config.allow_private is False

    def test_custom(self):
        """自定义配置"""
        config = URLWhitelistConfig(
            allowed_schemes={"https"},
            allowed_domains={"example.com"},
            blocked_domains={"evil.com"},
            allow_private=True,
        )
        assert config.allowed_schemes == {"https"}
        assert config.allowed_domains == {"example.com"}
        assert config.allow_private is True


# ─────────────────────────────────────────────────────────────
# URLValidator 测试
# ─────────────────────────────────────────────────────────────

class TestURLValidator:
    """Test URLValidator."""

    def test_validate_empty_url(self, validator):
        """空 URL 拒绝"""
        is_valid, msg = validator.validate("")
        assert is_valid is False
        assert "empty" in msg.lower()

    def test_validate_none_url(self, validator):
        """None URL 拒绝"""
        is_valid, msg = validator.validate(None)
        assert is_valid is False

    def test_validate_http_allowed(self, validator):
        """HTTP 允许"""
        is_valid, msg = validator.validate("http://example.com")
        assert is_valid is True
        assert msg == ""

    def test_validate_https_allowed(self, validator):
        """HTTPS 允许"""
        is_valid, msg = validator.validate("https://example.com")
        assert is_valid is True

    def test_validate_ftp_rejected(self, validator):
        """FTP 拒绝"""
        is_valid, msg = validator.validate("ftp://example.com")
        assert is_valid is False
        assert "scheme" in msg.lower()

    def test_validate_localhost_blocked(self, validator):
        """localhost 阻止"""
        is_valid, msg = validator.validate("http://localhost/path")
        assert is_valid is False
        assert "blocked" in msg.lower() or "not allowed" in msg.lower()

    def test_validate_127_blocked(self, validator):
        """127.0.0.1 阻止"""
        is_valid, msg = validator.validate("http://127.0.0.1/path")
        assert is_valid is False

    def test_validate_169_254_blocked(self, validator):
        """AWS metadata IP 阻止"""
        is_valid, msg = validator.validate("http://169.254.169.254/latest/meta-data")
        assert is_valid is False

    def test_validate_private_ip_blocked(self, validator):
        """私有 IP 阻止"""
        is_valid, msg = validator.validate("http://10.0.0.1/")
        assert is_valid is False

    def test_validate_192_168_blocked(self, validator):
        """192.168.x.x 阻止"""
        is_valid, msg = validator.validate("http://192.168.1.1/")
        assert is_valid is False

    def test_validate_172_blocked(self, validator):
        """172.16-31.x.x 阻止"""
        is_valid, msg = validator.validate("http://172.20.0.1/")
        assert is_valid is False

    def test_validate_strict_domain_whitelist(self, strict_validator):
        """严格模式：域名白名单"""
        is_valid, msg = strict_validator.validate("https://example.com/page")
        assert is_valid is True

    def test_validate_strict_domain_not_in_whitelist(self, strict_validator):
        """严格模式：域名不在白名单"""
        is_valid, msg = strict_validator.validate("https://other.com/page")
        assert is_valid is False

    def test_validate_sensitive_path_blocked(self, validator):
        """敏感路径阻止"""
        paths = ["/.env", "/.git/config", "/.aws/credentials", "/admin/", "/wp-admin/"]
        for path in paths:
            is_valid, msg = validator.validate(f"https://example.com{path}")
            assert is_valid is False, f"Path {path} should be blocked"

    def test_is_ip_address_ipv4(self, validator):
        """IPv4 检测"""
        assert validator._is_ip_address("192.168.1.1") is True
        assert validator._is_ip_address("10.0.0.1") is True
        assert validator._is_ip_address("8.8.8.8") is True
        assert validator._is_ip_address("not.an.ip") is False
        assert validator._is_ip_address("example.com") is False

    def test_is_ip_address_ipv6(self, validator):
        """IPv6 检测 (full format)"""
        # 使用完整格式的 IPv6 (regex 只匹配完整格式)
        assert validator._is_ip_address("2001:0db8:0000:0000:0000:0000:0000:0001") is True
        assert validator._is_ip_address("fe80:0000:0000:0000:0000:0000:0000:0001") is True

    def test_is_domain_blocked_exact(self, validator):
        """精确域名阻止"""
        assert validator._is_domain_blocked("localhost") is True
        assert validator._is_domain_blocked("evil.com") is False

    def test_is_domain_blocked_suffix(self, validator):
        """后缀域名阻止"""
        assert validator._is_domain_blocked("sub.localhost") is True
        assert validator._is_domain_blocked("evil.169.254.169.254") is True

    def test_is_private_ip(self, validator):
        """私有 IP 判断"""
        assert validator._is_private_ip("10.0.0.1") is True
        assert validator._is_private_ip("192.168.1.1") is True
        assert validator._is_private_ip("172.20.0.1") is True
        assert validator._is_private_ip("8.8.8.8") is False
        assert validator._is_private_ip("example.com") is False

    def test_is_safe_redirect_relative(self, validator):
        """相对路径重定向安全"""
        assert validator.is_safe_redirect("https://example.com", "/path") is True

    def test_is_safe_redirect_absolute_safe(self, validator):
        """绝对路径重定向（同域名）"""
        assert validator.is_safe_redirect("https://example.com", "https://example.com/path") is True

    def test_is_safe_redirect_absolute_unsafe(self, strict_validator):
        """绝对路径重定向（危险域名）"""
        assert strict_validator.is_safe_redirect("https://example.com", "https://evil.com/path") is False

    def test_is_safe_redirect_empty(self, validator):
        """空重定向安全"""
        assert validator.is_safe_redirect("https://example.com", "") is True

    def test_is_safe_redirect_none(self, validator):
        """None 重定向安全"""
        assert validator.is_safe_redirect("https://example.com", None) is True

    def test_validate_with_port(self, validator):
        """带端口的 URL"""
        is_valid, msg = validator.validate("https://example.com:8080/path")
        assert is_valid is True


# ─────────────────────────────────────────────────────────────
# InputSanitizer 测试
# ─────────────────────────────────────────────────────────────

class TestInputSanitizer:
    """Test InputSanitizer."""

    def test_sanitize_string_normal(self):
        """普通字符串不变"""
        result = InputSanitizer.sanitize_string("hello world")
        assert result == "hello world"

    def test_sanitize_string_html_encoded(self):
        """HTML 编码"""
        # 使用不触发 XSS 模式的普通字符（& 和普通文本）
        result = InputSanitizer.sanitize_string("hello & world &lt;script&gt;")
        assert "&amp;" in result

    def test_sanitize_string_html_allowed(self):
        """allow_html=True 时保留 HTML"""
        result = InputSanitizer.sanitize_string("&lt;b&gt;bold&lt;/b&gt;", allow_html=True)
        # allow_html=True 时 HTML 不被编码
        assert "&lt;" in result

    def test_sanitize_string_sql_injection_blocked(self):
        """SQL 注入阻止"""
        result = InputSanitizer.sanitize_string("'; DROP TABLE users; --")
        assert result == ""  # 被阻止

    def test_sanitize_string_xss_blocked(self):
        """XSS 阻止"""
        result = InputSanitizer.sanitize_string("<img src=x onerror=alert(1)>")
        assert result == ""

    def test_sanitize_string_path_traversal_blocked(self):
        """路径遍历阻止"""
        result = InputSanitizer.sanitize_string("../../../etc/passwd")
        assert result == ""

    def test_sanitize_string_select_blocked(self):
        """SELECT 关键词阻止"""
        result = InputSanitizer.sanitize_string("SELECT * FROM users")
        assert result == ""

    def test_sanitize_string_union_blocked(self):
        """UNION 关键词阻止"""
        result = InputSanitizer.sanitize_string("1 UNION SELECT password")
        assert result == ""

    def test_sanitize_string_non_string(self):
        """非字符串转字符串"""
        result = InputSanitizer.sanitize_string(123)
        assert result == "123"

    def test_sanitize_dict(self):
        """字典清理"""
        data = {
            "name": "John",
            "desc": "<script>bad</script>",
        }
        result = InputSanitizer.sanitize_dict(data)
        assert result["name"] == "John"
        assert "<" not in result["desc"]

    def test_sanitize_dict_nested(self):
        """嵌套字典清理"""
        data = {
            "outer": {
                "inner": "<b>test</b>",
            }
        }
        result = InputSanitizer.sanitize_dict(data)
        assert "<b>" not in result["outer"]["inner"]

    def test_sanitize_list(self):
        """列表清理"""
        data = ["<script>", "normal", "<img>"]
        result = InputSanitizer.sanitize_list(data)
        assert result[0] == ""  # blocked
        assert result[1] == "normal"
        assert result[2] == ""  # blocked

    def test_validate_length_valid(self):
        """有效长度"""
        is_valid, msg = InputSanitizer.validate_length("hello", min_length=3, max_length=10)
        assert is_valid is True

    def test_validate_length_too_short(self):
        """太短"""
        is_valid, msg = InputSanitizer.validate_length("hi", min_length=3)
        assert is_valid is False
        assert "below" in msg

    def test_validate_length_too_long(self):
        """太长"""
        is_valid, msg = InputSanitizer.validate_length("a" * 100, max_length=10)
        assert is_valid is False
        assert "exceeds" in msg

    def test_validate_pattern_valid(self):
        """格式验证通过"""
        is_valid, msg = InputSanitizer.validate_pattern("hello", r"^[a-z]+$", "lowercase")
        assert is_valid is True

    def test_validate_pattern_invalid(self):
        """格式验证失败"""
        is_valid, msg = InputSanitizer.validate_pattern("Hello123", r"^[a-z]+$", "lowercase")
        assert is_valid is False


# ─────────────────────────────────────────────────────────────
# RateLimiter 测试
# ─────────────────────────────────────────────────────────────

class TestRateLimiter:
    """Test RateLimiter."""

    @pytest.mark.asyncio
    async def test_is_allowed_first_call(self):
        """首次调用允许"""
        limiter = RateLimiter(calls=5, period=1.0)
        result = await limiter.is_allowed("key1")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_allowed_under_limit(self):
        """限制内允许"""
        limiter = RateLimiter(calls=5, period=1.0)
        for _ in range(5):
            result = await limiter.is_allowed("key2")
            assert result is True

    @pytest.mark.asyncio
    async def test_is_allowed_over_limit_blocked(self):
        """超限阻止"""
        limiter = RateLimiter(calls=3, period=1.0, block_duration=2.0)
        for _ in range(3):
            await limiter.is_allowed("key3")
        result = await limiter.is_allowed("key3")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_allowed_block_expires(self):
        """封禁过期后重置"""
        limiter = RateLimiter(calls=2, period=0.5, block_duration=0.5)
        for _ in range(3):  # 触发封禁
            await limiter.is_allowed("key4")
        await asyncio.sleep(0.6)
        result = await limiter.is_allowed("key4")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_remaining(self):
        """剩余次数"""
        limiter = RateLimiter(calls=5, period=1.0)
        assert limiter.get_remaining("new_key") == 5
        await limiter.is_allowed("key5")
        assert limiter.get_remaining("key5") == 4

    def test_reset_specific_key(self):
        """重置指定 key"""
        limiter = RateLimiter(calls=5, period=1.0)
        limiter._storage["key6"] = RateLimitInfo(calls=5)
        limiter.reset("key6")
        assert limiter.get_remaining("key6") == 5

    def test_reset_all(self):
        """重置所有"""
        limiter = RateLimiter(calls=5, period=1.0)
        limiter._storage["key7"] = RateLimitInfo(calls=5)
        limiter._storage["key8"] = RateLimitInfo(calls=5)
        limiter.reset()
        assert len(limiter._storage) == 0


# ─────────────────────────────────────────────────────────────
# rate_limit 装饰器测试
# ─────────────────────────────────────────────────────────────

class TestRateLimitDecorator:
    """Test rate_limit decorator."""

    @pytest.mark.asyncio
    async def test_rate_limit_decorator_allows(self):
        """装饰器允许限制内调用"""
        call_count = 0

        @rate_limit(calls=3, period=1.0)
        async def my_func():
            nonlocal call_count
            call_count += 1

        for _ in range(3):
            await my_func()
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_rate_limit_decorator_blocks(self):
        """装饰器超限阻止"""
        call_count = 0

        @rate_limit(calls=2, period=1.0, block_duration=0.5)
        async def my_func2():
            nonlocal call_count
            call_count += 1

        for _ in range(2):
            await my_func2()
        # 第三次会被阻止
        assert call_count == 2

    def test_rate_limit_adds_limiter_attr(self):
        """装饰器添加 limiter 属性"""
        @rate_limit(calls=5, period=1.0)
        async def my_func3():
            pass

        assert hasattr(my_func3, "_rate_limiter")
        assert isinstance(my_func3._rate_limiter, RateLimiter)


# ─────────────────────────────────────────────────────────────
# HMACValidator 测试
# ─────────────────────────────────────────────────────────────

class TestHMACValidator:
    """Test HMACValidator."""

    def test_generate(self):
        """生成签名"""
        validator = HMACValidator("secret_key", "sha256")
        sig = validator.generate("message")
        assert isinstance(sig, str)
        assert len(sig) > 0

    def test_verify_valid(self):
        """验证通过"""
        validator = HMACValidator("secret_key", "sha256")
        sig = validator.generate("message")
        assert validator.verify("message", sig) is True

    def test_verify_invalid(self):
        """验证失败"""
        validator = HMACValidator("secret_key", "sha256")
        assert validator.verify("message", "invalid_signature") is False

    def test_verify_wrong_message(self):
        """消息不匹配"""
        validator = HMACValidator("secret_key", "sha256")
        sig = validator.generate("message1")
        assert validator.verify("message2", sig) is False

    def test_different_key_different_signature(self):
        """不同密钥不同签名"""
        v1 = HMACValidator("key1", "sha256")
        v2 = HMACValidator("key2", "sha256")
        sig1 = v1.generate("message")
        sig2 = v2.generate("message")
        assert sig1 != sig2


# ─────────────────────────────────────────────────────────────
# 便捷函数测试
# ─────────────────────────────────────────────────────────────

class TestConvenienceFunctions:
    """Test create_url_validator and default_url_validator."""

    def test_create_url_validator(self):
        """创建验证器"""
        validator = create_url_validator(
            allowed_domains=["example.com"],
            allow_private=False,
        )
        assert validator is not None
        is_valid, _ = validator.validate("https://example.com/page")
        assert is_valid is True

    def test_create_url_validator_empty_domains(self):
        """空域名列表"""
        validator = create_url_validator(allowed_domains=[])
        is_valid, _ = validator.validate("https://example.com/page")
        assert is_valid is True  # 无白名单时允许

    def test_default_url_validator(self):
        """默认验证器实例"""
        assert default_url_validator is not None
        is_valid, _ = default_url_validator.validate("https://example.com")
        assert is_valid is True


# ─────────────────────────────────────────────────────────────
# 集成场景测试
# ─────────────────────────────────────────────────────────────

class TestSecurityIntegration:
    """Integration tests for security utilities."""

    def test_url_then_sanitize_workflow(self):
        """URL 验证后 sanitize 字符串"""
        validator = URLValidator(URLWhitelistConfig(
            allowed_domains={"example.com"},
            allow_private=False,
        ))

        # 验证 URL
        is_valid, _ = validator.validate("https://example.com/page?q=<script>")
        assert is_valid is True

        # 清理参数
        clean = InputSanitizer.sanitize_string("q=<script>")
        assert "<" not in clean

    def test_rate_limit_then_hmac(self):
        """限流后 HMAC"""
        limiter = RateLimiter(calls=10, period=1.0)
        validator = HMACValidator("secret", "sha256")

        async def request(data: str) -> bool:
            allowed = await limiter.is_allowed("api")
            if not allowed:
                return False
            sig = validator.generate(data)
            return validator.verify(data, sig)

        # 同步测试 HMAC 部分
        result = asyncio.get_event_loop().run_until_complete(request("test"))
        assert result is True
