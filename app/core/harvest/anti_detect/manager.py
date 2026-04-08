"""AntiDetectManager 统一入口与 Playwright 集成适配器"""

import asyncio
import math
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.harvest.anti_detect.behavior import AdaptiveLearningEngine, HumanBehaviorSimulator
from app.core.harvest.anti_detect.canvas import CanvasNoiseInjector
from app.core.harvest.anti_detect.dns import DNSLeakProtector
from app.core.harvest.anti_detect.fingerprints import FingerprintProfile
from app.core.harvest.anti_detect.tls import TLSFingerprintSimulator


class AntiDetectManager:
    """
    反检测系统统一管理器。

    整合 FingerprintProfile、CanvasNoiseInjector、
    TLSFingerprintSimulator、DNSLeakProtector、
    HumanBehaviorSimulator、AdaptiveLearningEngine，
    为每一次采集请求提供完整的反检测保护。
    """

    def __init__(
        self,
        fingerprint_pool_size: int = 10,
        enable_doh: bool = True,
        doh_provider: str = "cloudflare",
        enable_tls_sim: bool = True,
        persistence_path: Optional[str] = None,
        seed: Optional[int] = None,
    ):
        self.rng = np.random.default_rng(seed)

        # ── 子模块初始化 ────────────────────────────────────
        self.fingerprint_mgr  = FingerprintProfile(seed=seed)
        self.fingerprint_pool = self.fingerprint_mgr.build_pool(size=fingerprint_pool_size)
        self._fp_idx = 0

        self.canvas_noise = CanvasNoiseInjector(seed=seed)
        self.tls_sim      = TLSFingerprintSimulator(seed=seed)
        self.tls_sim.select_pattern()

        self.dns_protector = DNSLeakProtector(
            provider=doh_provider, mode="doh"
        ) if enable_doh else None

        self.human_behavior = HumanBehaviorSimulator(seed=seed)
        self.learner        = AdaptiveLearningEngine(seed=seed)

        self.persistence_path = persistence_path

        if persistence_path and os.path.exists(persistence_path):
            try:
                self.learner.import_data(persistence_path)
            except Exception:
                pass

    def get_fingerprint(self) -> Dict[str, Any]:
        """获取下一个指纹（池中轮换）。"""
        fp = self.fingerprint_pool[self._fp_idx % len(self.fingerprint_pool)]
        self._fp_idx += 1
        return fp

    async def apply_fingerprint(self, page) -> Dict[str, Any]:
        """将当前指纹配置应用到 Playwright page。"""
        fp = self.get_fingerprint()

        await page.set_extra_http_headers(fp.get("extra_http_headers", {}))
        await page.set_viewport_size(fp["screen"])
        await self.canvas_noise.inject(page)

        tz = fp["timezone"]
        await page.evaluate(f"""
            Intl.DateTimeFormat.prototype.resolvedOptions =
            function() {{
                return Object.assign(
                    Object.getPrototypeOf(this)(),
                    {{ timeZone: "{tz['id']}" }}
                );
            }};
        """)
        try:
            await page.context.set_timezone(tz["id"])
        except Exception:
            pass

        return fp

    def get_tls_config(self) -> Dict[str, Any]:
        return self.tls_sim.get_tls_config()

    def get_tls_headers(self) -> Dict[str, str]:
        return self.tls_sim.headers_for_pattern()

    def get_doh_config(self) -> Dict[str, str]:
        if self.dns_protector:
            return self.dns_protector.get_httpx_doh_session_config()
        return {}

    async def human_delay(self, action: str = "page_turn") -> None:
        """执行一个符合人类分布的延迟。"""
        params = self.learner.get_tuned_params("global")
        if action == "page_turn":
            base = params["live_delay_ms"] / 1000.0
            sigma = params.get("live_delay_ms", 800) / 1000.0 * 0.4
            delay = self.rng.lognormal(
                mean=math.log(base) if base > 0 else 0,
                sigma=sigma / base if base > 0 else 0.5,
            )
            await asyncio.sleep(float(np.clip(delay, base * 0.5, base * 3)))
        else:
            await self.human_behavior.async_delay(action)

    def record_result(
        self,
        source: str,
        http_status: int,
        success: bool,
        latency_ms: float,
        ban_detected: bool = False,
        captcha_seen: bool = False,
        fingerprint: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录一次采集行为的结果，触发自适应调参。"""
        fp_dict = fingerprint or self.get_fingerprint()

        bf = self.learner.BehaviorFingerprint(
            delay_mean_ms   = self.learner._live_params["delay_mean_ms"],
            delay_sigma_ms  = self.learner._live_params["delay_sigma_ms"],
            mouse_speed     = self.learner._live_params.get("mouse_speed_px_per_s", 200.0),
            click_noise_px  = self.learner._live_params["click_noise_px"],
            scroll_steps    = self.learner._live_params["scroll_steps"],
            fingerprint_id  = self.fingerprint_mgr.get_fingerprint_hash(fp_dict),
            tls_pattern     = self.tls_sim._active_pattern["name"]
                             if self.tls_sim._active_pattern else "unknown",
            doh_provider    = self.learner._live_params["doh_provider"],
        )

        self.learner.record(
            fingerprint=bf,
            source=source,
            http_status=http_status,
            success=success,
            latency_ms=latency_ms,
            ban_detected=ban_detected,
            captcha_seen=captcha_seen,
        )

        if self.persistence_path and self.learner._total_requests % 100 == 0:
            self.learner.export(self.persistence_path)

    def health_report(self) -> Dict[str, Any]:
        return self.learner.health_metrics()

    def get_recommended_config(self, source: str) -> Dict[str, Any]:
        return self.learner.recommend_behavior_config(source)


class PlaywrightAntiDetectAdapter:
    """
    Playwright + AntiDetectManager 集成适配器。

    封装常用 Playwright 操作（goto, click, scroll 等），
    自动注入反检测逻辑，无需每次手动调用。
    """

    def __init__(self, manager: AntiDetectManager):
        self.manager = manager

    async def safe_goto(
        self,
        page,
        url: str,
        source: str,
        wait_until: str = "domcontentloaded",
        timeout: float = 30_000.0,
    ) -> Tuple[Optional[Dict[str, Any]], bool]:
        """带反检测保护的页面跳转。 Returns: (fingerprint_used, ban_detected)"""
        start = time.monotonic()
        ban_detected = False

        fp = await self.manager.apply_fingerprint(page)

        try:
            response = await page.goto(url, wait_until=wait_until, timeout=timeout)
            status = response.status if response else 0
            latency_ms = (time.monotonic() - start) * 1000

            if status in (403, 401):
                ban_detected = True
            elif status == 429:
                ban_detected = True

            self.manager.record_result(
                source=source,
                http_status=status,
                success=(200 <= status < 300),
                latency_ms=latency_ms,
                ban_detected=ban_detected,
                fingerprint=fp,
            )
            return fp, ban_detected

        except Exception:
            self.manager.record_result(
                source=source,
                http_status=0,
                success=False,
                latency_ms=(time.monotonic() - start) * 1000,
                ban_detected=True,
                fingerprint=fp,
            )
            raise

    async def safe_click(self, page, selector: str, sigma: Optional[float] = None) -> None:
        """带人类噪声的点击。"""
        if sigma is None:
            params = self.manager.learner.get_tuned_params("global")
            sigma = params.get("click_noise_px", 8.0)
        await self.manager.human_behavior.human_click(page, selector, sigma=sigma)

    async def safe_scroll(self, page, start_y: int = 0, end_y: int = 800) -> None:
        """带非线性减速曲线的滚动。"""
        params = self.manager.learner.get_tuned_params("global")
        await self.manager.human_behavior.human_scroll(
            page, start_y, end_y, num_steps=params.get("scroll_steps", 30),
        )

    async def browse_sequence(self, page, selectors: List[str], source: str) -> None:
        """执行完整的人类浏览序列。"""
        await self.manager.human_delay("think")
        for sel in selectors:
            try:
                box = await page.locator(sel).bounding_box()
                if box is None:
                    continue
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                params = self.manager.learner.get_tuned_params(source)
                await self.manager.human_behavior.human_mouse_move(
                    page,
                    start=(int(cx) - 100, int(cy) - 50),
                    end=(int(cx), int(cy)),
                    duration_ms=600.0,
                )
                await self.manager.human_delay("hover")
                await self.safe_click(page, sel)
                await self.manager.human_delay("page_turn")
            except Exception:
                await page.locator(sel).click()
                await self.manager.human_delay("page_turn")
