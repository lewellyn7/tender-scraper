"""浏览器指纹生成与管理"""

import hashlib
import json
from typing import Any, Dict, List, Optional

import numpy as np


class FingerprintProfile:
    """
    浏览器指纹配置管理器。

    支持指纹生成（随机）、指纹池（固定轮换）和自定义覆盖。
    所有指纹参数均以真实浏览器为基准进行建模。
    """

    # ── 真实浏览器 UA 库（按类型/版本/平台分层）────────────────
    CHROME_UA_POOL: List[str] = [
        # Windows Chrome 122-125
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        # macOS Chrome 122-124
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        # Edge (Chromium) 122-124
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
        # Firefox 123-124 (备用)
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
        "Gecko/20100101 Firefox/124.0",
    ]

    SCREEN_POOL: List[Dict[str, int]] = [
        # 主流分辨率
        {"width": 1920, "height": 1080, "deviceScaleFactor": 1},
        {"width": 1536, "height": 864,  "deviceScaleFactor": 1},
        {"width": 1366, "height": 768,  "deviceScaleFactor": 1},
        {"width": 1440, "height": 900,  "deviceScaleFactor": 1},
        # HiDPI
        {"width": 2560, "height": 1440, "deviceScaleFactor": 2},
    ]

    TIMEZONE_POOL: List[Dict[str, Any]] = [
        {"id": "Asia/Shanghai",  "offset": 480,  "name": "China (Shanghai)"},
        {"id": "Asia/Chongqing", "offset": 480,  "name": "China (Chongqing)"},
        {"id": "Asia/Hong_Kong", "offset": 480,  "name": "Hong Kong"},
        {"id": "Asia/Beijing",   "offset": 480,  "name": "China (Beijing)"},
        {"id": "Asia/Nanjing",   "offset": 480,  "name": "China (Nanjing)"},
    ]

    # 常见 Accept-Language 组合
    LANG_POOL: List[str] = [
        "zh-CN,zh;q=0.9,en;q=0.8",
        "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "zh,zh-CN;q=0.9,en;q=0.8",
        "zh-CN;q=0.9",
    ]

    # Platform 值（Windows 平台 Chrome）
    PLATFORM_POOL: List[str] = [
        "Win32",
        "MacIntel",      # macOS Intel
        "Macintosh; Intel Mac OS X 10_15_7",
    ]

    # WebGL 渲染器 / 供应商（真实 GPU 型号池）
    WEBGL_POOL: List[Dict[str, str]] = [
        {"vendor": "Google Inc. (NVIDIA)",
         "renderer": "ANGLE (NVIDIA GeForce GTX 1060 Direct3D11 vs_5_0 ps_5_0)"},
        {"vendor": "Google Inc. (Intel)",
         "renderer": "ANGLE (Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0)"},
        {"vendor": "Google Inc. (AMD)",
         "renderer": "ANGLE (AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0)"},
        {"vendor": "Google Inc. (Intel)",
         "renderer": "ANGLE (Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0)"},
        {"vendor": "Intel Inc.",
         "renderer": "Intel Iris OpenGL Engine"},
    ]

    # Canvas 基础噪声幅度（相对噪声，0=无噪声）
    CANVAS_NOISE_SCALE: float = 0.0005  # ~0.05% 偏移（肉眼不可见，算法可检测）

    def __init__(self, seed: Optional[int] = None):
        self.rng = np.random.default_rng(seed)
        self._profile_cache: Dict[str, Dict[str, Any]] = {}
        self._profile_id_counter = 0

    # ── 核心：生成完整指纹配置 ───────────────────────────────
    def generate(self, persona_type: str = "default") -> Dict[str, Any]:
        """
        生成一个完整的浏览器指纹配置。

        Args:
            persona_type: "default" | "mobile" | "stealth"
        Returns:
            包含所有指纹字段的字典，可直接注入 Playwright page.
        """
        ua = self.rng.choice(self.CHROME_UA_POOL)
        screen = self.rng.choice(self.SCREEN_POOL)
        tz = self.rng.choice(self.TIMEZONE_POOL)
        lang = self.rng.choice(self.LANG_POOL)
        platform = self.rng.choice(self.PLATFORM_POOL)
        webgl = self.rng.choice(self.WEBGL_POOL)

        profile = {
            # ── 基础指纹 ─────────────────────────────────────
            "user_agent": ua,
            "platform":   platform,
            "screen":     screen,
            "timezone":   tz,
            "locale":     lang.split(",")[0],  # "zh-CN"
            "languages":  lang,
            # ── WebGL ─────────────────────────────────────────
            "webgl_vendor":   webgl["vendor"],
            "webgl_renderer": webgl["renderer"],
            # ── 额外属性（Playwright extra HTTP headers）───────
            "extra_http_headers": {
                "Accept-Language": lang,
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,image/apng,*/*;q=0.8"
                ),
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            },
        }
        pid = self._profile_id_counter
        self._profile_id_counter += 1
        self._profile_cache[str(pid)] = profile
        return profile

    # ── 预生成指纹池（启动时生成 N 个，轮换使用）─────────────
    def build_pool(self, size: int = 10,
                   persona_type: str = "default") -> List[Dict[str, Any]]:
        """预生成固定池，轮换使用避免同一 IP 指纹重复。"""
        return [self.generate(persona_type) for _ in range(size)]

    def get_fingerprint_hash(self, profile: Dict[str, Any]) -> str:
        """计算指纹摘要（用于去重/对比）。"""
        key = json.dumps(profile, sort_keys=True, default=str)
        return hashlib.sha256(key.encode()).hexdigest()[:16]
