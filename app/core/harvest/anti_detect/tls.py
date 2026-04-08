"""TLS 指纹模拟 (JA3/JA3N/JA4) 与 curl_cffi 集成"""

from typing import Any, Dict, List, Optional

import numpy as np


class TLSFingerprintSimulator:
    """
    TLS 指纹模拟器。

    不依赖外部代理，而是通过调整 Python requests / httpx 的
    HTTP2/TLS 配置来模拟主流浏览器 TLS 指纹，降低被识别概率。

    JA3/JA3N/JA4 指纹由 TLS ClientHello 字段决定：
      - TLS 版本
      - 加密套件列表顺序
      - 椭圆曲线 / 扩展顺序
      - SNI 主机名字符串

    我们维护一份"真实浏览器 JA3 指纹库"，在请求时随机选择一个
    进行模拟（通过修改 httpx / curl_cffi 的 ALPN 行为）。

    警告：完整 JA3 模拟需要底层 SSL 库定制，当前方案通过
          调整 HTTP 头和 TLS 版本/扩展配置来近似。
    """

    # 主流浏览器 JA3 参考（简化版，仅 TLS 版本+加密套件列表顺序）
    BROWSER_JA3_PATTERNS: List[Dict[str, Any]] = [
        {
            "name": "chrome_124_win",
            "tls_version": "TLS 1.3",
            "cipher_suites": [
                0x1301, 0x1302, 0x1303,   # TLS 1.3 cipher suites
                0x002F, 0x0035,           # TLS 1.2 RSA cipher suites
                0xC02C, 0xC030,           # ECDHE cipher suites
            ],
            "alpn": ["h2", "http/1.1"],
            "sni_enabled": True,
            "ja4": "t13d1518h2_8c3a5d9e7f0_b57c6d9e8a4",
        },
        {
            "name": "chrome_123_mac",
            "tls_version": "TLS 1.3",
            "cipher_suites": [
                0x1301, 0x1303, 0x1302,
                0x002F, 0x0035,
                0xC02C, 0xC030,
            ],
            "alpn": ["h2", "http/1.1"],
            "sni_enabled": True,
            "ja4": "t13d1518h2_9c3a5d9e7f0_a27c6d9e8a4",
        },
        {
            "name": "edge_124_win",
            "tls_version": "TLS 1.3",
            "cipher_suites": [
                0x1301, 0x1302, 0x1303,
                0x002F, 0x0035,
                0xC02C, 0xC030, 0x00A0,
            ],
            "alpn": ["h2", "http/1.1"],
            "sni_enabled": True,
            "ja4": "t13d1518h2_c3a5d9e7f0_b57c6d9e8a4",
        },
        {
            "name": "firefox_124_win",
            "tls_version": "TLS 1.3",
            "cipher_suites": [
                0x1301, 0x1303, 0x1302,
                0x002F, 0x0035,
                0xC02C,
            ],
            "alpn": ["h2", "http/1.1"],
            "sni_enabled": True,
            "ja4": "t13d1518h2_d3a5d9e7f0_c37c6d9e8a4",
        },
    ]

    def __init__(self, seed: Optional[int] = None):
        self.rng = np.random.default_rng(seed)
        self._active_pattern: Optional[Dict[str, Any]] = None

    def select_pattern(self) -> Dict[str, Any]:
        """随机选择一个浏览器 TLS 模式。"""
        self._active_pattern = self.rng.choice(self.BROWSER_JA3_PATTERNS)
        return self._active_pattern

    def get_tls_config(self) -> Dict[str, Any]:
        """
        返回当前 TLS 模式的配置字典，
        可注入到 httpx / requests 适配器。
        """
        if self._active_pattern is None:
            self.select_pattern()

        return {
            "tls_version": self._active_pattern["tls_version"],
            "alpn":        self._active_pattern["alpn"],
            "sni_enabled": self._active_pattern["sni_enabled"],
            "cipher_suites": self._active_pattern["cipher_suites"],
            "ja4":         self._active_pattern.get("ja4", "unknown"),
        }

    def headers_for_pattern(self) -> Dict[str, str]:
        """
        返回符合当前 TLS 模式的 HTTP 请求头。
        注意：这不能改变真实的 TLS 指纹，但可以配合绕过某些前端检测。
        """
        if self._active_pattern is None:
            self.select_pattern()

        p = self._active_pattern["name"]
        if "chrome" in p:
            return {
                "sec-ch-ua":        '"Google Chrome";v="124", "Not:A-Brand";v="8", "Chromium";v="124"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            }
        elif "edge" in p:
            return {
                "sec-ch-ua":        '"Microsoft Edge";v="124", "Not:A-Brand";v="8", "Chromium";v="124"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            }
        else:  # firefox
            return {
                "sec-ch-ua":        '"Firefox";v="124", "Not:A-Brand";v="8", "Gecko";v="124"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            }


# ─────────────────────────────────────────────────────────────
# TLS 指纹辅助工具（curl_cffi 集成示例）
# ─────────────────────────────────────────────────────────────


class TLSFingerprintForCurl:
    """
    通过 curl_cffi 绑定来模拟浏览器 TLS 指纹的示例。

    curl_cffi 可以劫持底层 libcurl 的 TLS 握手，
    从而实现 JA3/JA4 指纹级别的模拟。

    用法：
        from curl_cffi import requests
        tls_config = TLSFingerprintForCurl("chrome_124_win")
        session = requests.Session(impersonate=tls_config.impersonate_name)
        resp = session.get("https://target-site.com")
    """

    IMPERSONATE_MAP: Dict[str, str] = {
        "chrome_124_win":   "chrome124",
        "chrome_123_mac":  "chrome123",
        "edge_124_win":    "edge124",
        "firefox_124_win": "firefox124",
    }

    def __init__(self, pattern_name: str = "chrome_124_win"):
        self.pattern_name = pattern_name
        self.impersonate_name = self.IMPERSONATE_MAP.get(
            pattern_name, "chrome124"
        )

    def as_curl_cffi_session_kwargs(self) -> Dict[str, Any]:
        return {
            "impersonate": self.impersonate_name,
            "verify": False,  # 内部测试用
            "timeout": 30,
        }
