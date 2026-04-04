"""安全工具测试 - utils 模块"""

def test_rate_limiter():
    from app.utils.security import RateLimiter
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    allowed, remaining = limiter.is_allowed("test_key")
    assert allowed == True
    assert remaining == 2

def test_validate_url():
    from app.utils.security import validate_url
    assert validate_url("https://example.com") == True
    assert validate_url("not-a-url") == False

def test_validate_email():
    from app.utils.security import validate_email
    assert validate_email("test@example.com") == True
    assert validate_email("invalid") == False

def test_rate_limiter_exceed_limit():
    from app.utils.security import RateLimiter
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    # 前两次允许
    allowed1, _ = limiter.is_allowed("burst_key")
    allowed2, _ = limiter.is_allowed("burst_key")
    # 第三次应该被拒绝
    allowed3, remaining = limiter.is_allowed("burst_key")
    assert allowed1 == True
    assert allowed2 == True
    assert allowed3 == False
    assert remaining == 0
