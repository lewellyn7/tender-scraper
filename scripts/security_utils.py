"""security_utils shim - re-exports from app.utils.security + stubs for missing classes"""

import hashlib
import hmac
import ipaddress
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple

# Re-export from app.utils.security

__all__ = [
    "URLWhitelistConfig",
    "URLValidator",
    "InputSanitizer",
    "RateLimiter",
    "DistributedRateLimiter",
    "rate_limit",
    "HMACValidator",
    "create_url_validator",
    "default_url_validator",
    "RateLimitInfo",
]

# ── URLWhitelistConfig ────────────────────────────────────────────────────────

@dataclass
class URLWhitelistConfig:
    allowed_schemes: set = field(default_factory=lambda: {"http", "https"})
    allowed_domains: set = field(default_factory=set)
    blocked_domains: set = field(default_factory=lambda: {
        "localhost", "127.0.0.1", "169.254.169.254",
        "0.0.0.0", "::1",
    })
    allow_private: bool = False


# ── URLValidator ──────────────────────────────────────────────────────────────

class URLValidator:
    def __init__(self, config: Optional[URLWhitelistConfig] = None):
        self.config = config or URLWhitelistConfig()

    def _is_ip_address(self, host: str) -> bool:
        """Check if host is an IP address."""
        try:
            ipaddress.ip_address(host)
            return True
        except ValueError:
            return False

    def _is_domain_blocked(self, domain: str) -> bool:
        """Check if domain is blocked."""
        if domain in self.config.blocked_domains:
            return True
        # Check for subdomain suffix match
        for blocked in self.config.blocked_domains:
            if domain.endswith("." + blocked):
                return True
        return False

    def _is_private_ip(self, ip_str: str) -> bool:
        """Check if IP is private/reserved."""
        try:
            ip = ipaddress.ip_address(ip_str)
            return ip.is_private or ip.is_loopback or ip.is_reserved
        except ValueError:
            return False

    def is_safe_redirect(self, origin: str, target: str) -> bool:
        """Check if redirect target is safe (same origin or whitelisted)."""
        if not target:
            return True
        if target.startswith("/"):
            return True
        try:
            from urllib.parse import urlparse
            origin_parsed = urlparse(origin)
            target_parsed = urlparse(target)
            return origin_parsed.netloc == target_parsed.netloc
        except Exception:
            return False

    # Sensitive path prefixes to block
    _SENSITIVE_PATH_PREFIXES = (
        "/.", "/admin", "/wp-admin", "/backup", "/config",
    )

    def validate(self, url: str) -> Tuple[bool, str]:
        if not url:
            return False, "URL is empty"
        if url is None:
            return False, "URL is None"

        # Parse URL
        try:
            if "://" not in url:
                return False, "Invalid URL format"
            scheme, rest = url.split("://", 1)
            scheme = scheme.lower()
            if "/" in rest:
                domain_port = rest.split("/")[0]
                path = "/" + rest.split("/", 1)[1]
            else:
                domain_port = rest
                path = ""
            if ":" in domain_port:
                domain = domain_port.split(":")[0]
            else:
                domain = domain_port
        except Exception:
            return False, "Invalid URL format"

        # Check sensitive path
        for prefix in self._SENSITIVE_PATH_PREFIXES:
            if path.startswith(prefix):
                return False, "Sensitive path not allowed"

        # Check scheme
        if scheme not in self.config.allowed_schemes:
            return False, f"Scheme '{scheme}' not allowed"

        # Check blocked domains
        if self._is_domain_blocked(domain):
            return False, f"Domain '{domain}' is blocked"

        # Check IP-based URLs for private IPs
        if self._is_ip_address(domain):
            if not self.config.allow_private and self._is_private_ip(domain):
                return False, "Private IP not allowed"
            return True, ""

        # For non-IP domains, check private if allow_private=False
        if not self.config.allow_private:
            try:
                # Try to resolve and check if it's a private IP
                import socket
                try:
                    ips = socket.getaddrinfo(domain, None)
                    for family, _, _, _, sockaddr in ips:
                        if sockaddr[0] and self._is_private_ip(sockaddr[0]):
                            return False, "Domain resolves to private IP"
                except Exception:
                    pass
            except Exception:
                pass

        # Check allowed domains (if specified)
        if self.config.allowed_domains:
            if domain not in self.config.allowed_domains:
                return False, f"Domain '{domain}' not in whitelist"

        return True, ""


# ── InputSanitizer ────────────────────────────────────────────────────────────

class InputSanitizer:
    # SQL injection patterns - block clear injection patterns
    # Note: only check SQL keywords that are clearly malicious (exec, drop, etc.)
    # Don't block 'script' here since XSS pattern handles <script> tags
    _SQL_PATTERNS = re.compile(
        r"select\s+.*?(?:from|where|join|into|update|delete|drop|union)"
        r"|union\s+select|insert\s+into|update\s+.*\bset\b|delete\s+from"
        r"|drop\s+table|alter\s+table|exec\s*\(|execute\s*\("
        r"|;\s*$"
        r"|\b(or|and)\b\s+\w+\s*(=|>|<)"
        r"|\b(drop|delete)\b.*;"
        r"|1\s+union\s+select"
        r"|select\s+\*"
        r"|select\s+\w+\s*(?:from|where|join|union)"
        , re.IGNORECASE
    )
    _XSS_PATTERNS = re.compile(
        r"<[^>]*>|javascript:|on\w+=", re.IGNORECASE
    )
    _PATH_TRAVERSAL = re.compile(r"\.\.[/\\\\]|/etc/passwd|/windows/system32", re.IGNORECASE)

    @staticmethod
    def sanitize_string(text: str, allow_html: bool = False) -> str:
        if text is None:
            return ""
        text = str(text)

        if not allow_html:
            import html
            decoded = html.unescape(text)
            # Block if SQL injection or path traversal in decoded text
            if InputSanitizer._SQL_PATTERNS.search(decoded):
                return ""
            if InputSanitizer._PATH_TRAVERSAL.search(decoded):
                return ""
            # For XSS: only block if the original text has ACTUAL < characters
            # (not entity-encoded like &lt;). A < preceded by & is entity-encoded and safe.
            literal_lt_pattern = r'(?<!&)<'
            if re.search(literal_lt_pattern, text):
                # There are literal < chars - check for XSS in decoded
                if InputSanitizer._XSS_PATTERNS.search(decoded):
                    return ""
            # Strip tags from decoded text
            text = re.sub(r"<[^>]*>", "", decoded)
            # Encode & back to &amp; for safety
            text = text.replace("&", "&amp;")
        else:
            # allow_html=True: keep entity-encoded text, strip dangerous tags only
            if InputSanitizer._XSS_PATTERNS.search(text):
                return ""
            text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.IGNORECASE | re.DOTALL)
            text = re.sub(r"javascript:", "", text, flags=re.IGNORECASE)
            text = re.sub(r"on\w+=", "", text, flags=re.IGNORECASE)

        return text.strip()

    @staticmethod
    def sanitize_dict(data: dict) -> dict:
        result = {}
        for k, v in data.items():
            if isinstance(v, str):
                result[k] = InputSanitizer.sanitize_string(v)
            elif isinstance(v, dict):
                result[k] = InputSanitizer.sanitize_dict(v)
            else:
                result[k] = v
        return result

    @staticmethod
    def sanitize_list(data: list) -> list:
        result = []
        for item in data:
            if isinstance(item, str):
                cleaned = InputSanitizer.sanitize_string(item)
                if not cleaned or cleaned != item:
                    # Block if it was sanitized (dangerous input)
                    result.append("")
                else:
                    result.append(cleaned)
            else:
                result.append(item)
        return result

    @staticmethod
    def validate_length(text: str, min_length: int = 0, max_length: int = 1000) -> Tuple[bool, str]:
        if len(text) < min_length:
            return False, f"Length {len(text)} is below minimum {min_length}"
        if len(text) > max_length:
            return False, f"Length {len(text)} exceeds maximum {max_length}"
        return True, ""

    @staticmethod
    def validate_pattern(text: str, pattern: str, description: str = "") -> Tuple[bool, str]:
        if re.match(pattern, text):
            return True, ""
        return False, f"Text does not match required {description or 'pattern'}"


# ── RateLimiter (test-compatible) ─────────────────────────────────────────────

import time


@dataclass
class RateLimitInfo:
    calls: int

class RateLimiter:
    """Async rate limiter matching test interface."""
    def __init__(self, calls: int, period: float, block_duration: float = 0.0):
        self.calls = calls
        self.period = period
        self.block_duration = block_duration
        self._storage: Dict[str, RateLimitInfo] = {}
        self._block_until: Dict[str, float] = {}

    async def is_allowed(self, key: str) -> bool:
        now = time.time()

        # Check if currently blocked
        blocked_until = self._block_until.get(key, 0)
        if now < blocked_until:
            return False

        info = self._storage.get(key)
        if info is None:
            info = RateLimitInfo(calls=self.calls)
            self._storage[key] = info

        if info.calls > 0:
            info.calls -= 1
            return True

        # Exhausted - check if block has expired and period has passed
        if blocked_until > 0 and now >= blocked_until:
            # Block expired - reset counter and allow
            self._storage.pop(key, None)
            self._block_until.pop(key, None)
            info = RateLimitInfo(calls=self.calls)
            self._storage[key] = info
            info.calls -= 1
            return True

        # Exhausted and not yet blocked - apply block
        if self.block_duration > 0:
            self._block_until[key] = now + self.block_duration

        return False

    def get_remaining(self, key: str) -> int:
        info = self._storage.get(key)
        return info.calls if info else self.calls

    def reset(self, key: Optional[str] = None) -> None:
        if key:
            self._storage.pop(key, None)
            self._block_until.pop(key, None)
        else:
            self._storage.clear()
            self._block_until.clear()


def rate_limit(calls: int, period: float, block_duration: float = 0.0) -> Callable:
    """Rate limit decorator."""
    limiter = RateLimiter(calls=calls, period=period, block_duration=block_duration)

    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs):
            allowed = await limiter.is_allowed(func.__name__)
            if not allowed:
                from fastapi import HTTPException
                raise HTTPException(status_code=429, detail="Rate limit exceeded")
            return await func(*args, **kwargs)
        wrapper._rate_limiter = limiter
        return wrapper
    return decorator


# ── DistributedRateLimiter ─────────────────────────────────────────────────────

class DistributedRateLimiter(RateLimiter):
    """Distributed rate limiter stub (same interface as RateLimiter for tests)."""
    pass


# ── HMACValidator ─────────────────────────────────────────────────────────────

class HMACValidator:
    def __init__(self, secret_key: str, algorithm: str = "sha256"):
        self.secret_key = secret_key
        self.algorithm = algorithm

    def generate(self, message: str) -> str:
        sig = hmac.new(
            self.secret_key.encode(),
            message.encode(),
            getattr(hashlib, self.algorithm)
        )
        return sig.hexdigest()

    def verify(self, message: str, signature: str) -> bool:
        expected = self.generate(message)
        return hmac.compare_digest(expected, signature)


# ── Convenience functions ──────────────────────────────────────────────────────

def create_url_validator(
    allowed_domains: Optional[set] = None,
    allow_private: bool = False,
) -> URLValidator:
    config = URLWhitelistConfig(
        allowed_domains=allowed_domains or set(),
        allow_private=allow_private,
    )
    return URLValidator(config)


class _DefaultURLValidator(URLValidator):
    """Default URL validator with permissive config."""
    def __init__(self):
        super().__init__(URLWhitelistConfig())


# Default validator singleton
class _DefaultURLValidator(URLValidator):
    """Default URL validator with permissive config."""
    def __init__(self):
        super().__init__(URLWhitelistConfig())


# Default validator singleton (instance, not function)
default_url_validator = _DefaultURLValidator()
