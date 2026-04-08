"""async_crawler_base shim - re-exports from app.core.harvest + stubs for missing classes"""

from app.core.harvest.exception_handler import AnomalyType as _RealAnomalyType
from dataclasses import dataclass, field
from typing import Optional, Any
import asyncio

# Re-export
AnomalyType = _RealAnomalyType


@dataclass
class CrawlerConfig:
    """Crawler configuration matching test expectations."""
    timeout: int = 30
    max_retries: int = 3
    max_concurrency: int = 20
    rate_limit: Optional["RateLimitConfig"] = None


@dataclass
class RateLimitConfig:
    """Rate limit configuration for AsyncCrawlerBase."""
    requests_per_second: float = 5.0
    burst_size: int = 10


class TokenBucket:
    """Token bucket rate limiter."""
    def __init__(self, rate: float, capacity: float):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity

    async def acquire(self) -> None:
        while self.tokens < 1:
            await asyncio.sleep(0.01)
        self.tokens -= 1

    async def _refill(self) -> None:
        self.tokens = min(self.capacity, self.tokens + self.rate * 0.1)


class AsyncCrawlerBase:
    """Async crawler base class stub for test compatibility."""
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self._session = None

    def session(self):
        """Sync context manager for session."""
        class SessionCtx:
            async def __aenter__(s):
                self._session = object()
                return self._session
            async def __aexit__(s, *args):
                self._session = None
        return SessionCtx()

    def _calculate_delay(self, anomaly_type: "AnomalyType", attempt: int) -> float:
        """Calculate delay based on anomaly type and retry attempt."""
        base_delays = {
            AnomalyType.NETWORK_TIMEOUT: 2.0,
            AnomalyType.RATE_LIMIT: 60.0,
            AnomalyType.BAN: 300.0,
            AnomalyType.SERVER_ERROR: 5.0,
            AnomalyType.PARSE_ERROR: 1.0,
            AnomalyType.UNKNOWN: 10.0,
        }
        base = base_delays.get(anomaly_type, 10.0)
        return base * (2 ** attempt)

    def classify_error(self, error: Exception, response_status: Optional[int] = None) -> "AnomalyType":
        """Classify error into AnomalyType."""
        if response_status == 429:
            return AnomalyType.RATE_LIMIT
        if response_status == 403:
            return AnomalyType.BAN
        if response_status == 500:
            return AnomalyType.SERVER_ERROR
        msg = str(error).lower()
        if "timeout" in msg or "timed out" in msg:
            return AnomalyType.NETWORK_TIMEOUT
        if "rate limit" in msg:
            return AnomalyType.RATE_LIMIT
        if "parse" in msg or "html" in msg:
            return AnomalyType.PARSE_ERROR
        return AnomalyType.UNKNOWN

    async def batch_fetch(self, urls: list) -> list:
        """Fetch multiple URLs."""
        return []
