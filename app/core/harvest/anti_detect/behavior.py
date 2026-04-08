"""人类行为模拟与自适应学习引擎"""

import asyncio
import json
import math
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np


class HumanBehaviorSimulator:
    """
    人类行为模拟器。

    设计原则：所有时间/空间参数均从真实用户行为分布中采样，
    而非固定值或纯均匀随机。

    核心分布：
    - 页面间隔：右偏（正态对数分布），避免均匀等距
    - 鼠标轨迹：三阶贝塞尔曲线，起点→控制点→终点
    - 滚动：先快后慢，非线性减速曲线
    - 点击：中心 + 高斯噪声
    """

    def __init__(self, seed: Optional[int] = None):
        self.rng = np.random.default_rng(seed)

    # ── 时间间隔（非均匀分布：右偏对数正态）──────────────────
    def sample_interaction_delay(
        self,
        action: str = "page_turn",
        base_seconds: float = 2.0,
    ) -> float:
        """
        根据动作类型从真实分布中采样时间延迟。
        """
        presets = {
            "page_turn":   {"mu": 1.5, "sigma": 0.8, "min": 0.8,  "max": 12.0},
            "scroll_stop": {"mu": 0.3, "sigma": 0.5, "min": 0.1,  "max":  3.0},
            "search_key":  {"mu": 0.1, "sigma": 0.3, "min": 0.03, "max":  1.5},
            "hover":       {"mu": 0.5, "sigma": 0.4, "min": 0.1,  "max":  4.0},
            "think":       {"mu": 2.0, "sigma": 1.2, "min": 0.5,  "max": 20.0},
        }

        p = presets.get(action, {"mu": 1.0, "sigma": 1.0, "min": 0.5, "max": 10.0})
        delay = self.rng.lognormal(mean=p["mu"], sigma=p["sigma"])
        return float(np.clip(delay, p["min"], p["max"]))

    async def async_delay(self, action: str = "page_turn") -> None:
        """异步版本：执行一个符合人类行为分布的延迟。"""
        delay = self.sample_interaction_delay(action)
        jitter = self.rng.uniform(0.9, 1.1)
        await asyncio.sleep(delay * jitter)

    # ── 鼠标轨迹（三阶贝塞尔曲线）────────────────────────────
    def generate_bezier_mouse_track(
        self,
        start: Tuple[float, float],
        end:   Tuple[float, float],
        control_points: Optional[List[Tuple[float, float]]] = None,
        num_points: int = 20,
    ) -> List[Tuple[float, float]]:
        """生成三阶贝塞尔曲线鼠标轨迹。"""
        if control_points is None:
            dx, dy = end[0] - start[0], end[1] - start[1]
            dist   = math.sqrt(dx**2 + dy**2)
            perp_x, perp_y = -dy / (dist + 1e-6), dx / (dist + 1e-6)
            offset = self.rng.uniform(0.2, 0.6) * dist
            sign   = self.rng.choice([-1, 1])

            cp1 = (
                start[0] + dx * 0.25 + perp_x * offset * sign,
                start[1] + dy * 0.25 + perp_y * offset * sign,
            )
            cp2 = (
                start[0] + dx * 0.75 + perp_x * offset * sign * 0.5,
                start[1] + dy * 0.75 + perp_y * offset * sign * 0.5,
            )
        else:
            cp1, cp2 = control_points[0], control_points[1]

        def _bezier(p0, p1, p2, p3, t):
            mt = 1 - t
            return mt**3 * p0 + 3 * mt**2 * t * p1 + 3 * mt * t**2 * p2 + t**3 * p3

        pts = []
        for i in range(num_points + 1):
            t = i / num_points
            x = _bezier(start[0], cp1[0], cp2[0], end[0], t)
            y = _bezier(start[1], cp1[1], cp2[1], end[1], t)
            pts.append((round(x, 2), round(y, 2)))

        jitter = self.rng.normal(loc=0.0, scale=1.5, size=(len(pts), 2))
        pts = [(x + jitter[i, 0], y + jitter[i, 1]) for i, (x, y) in enumerate(pts)]
        return pts

    async def human_mouse_move(
        self,
        page,
        start: Tuple[int, int],
        end:   Tuple[int, int],
        duration_ms: float = 600.0,
    ) -> None:
        """通过 Playwright 执行人类风格鼠标移动。"""
        duration_ms = self.rng.uniform(400, 900)
        track = self.generate_bezier_mouse_track(start, end, num_points=24)
        step_delay = duration_ms / len(track)

        for x, y in track:
            await page.mouse.move(x, y)
            await asyncio.sleep(step_delay / 1000)

    # ── 点击位置噪声 ─────────────────────────────────────────
    def add_click_noise(self, x: float, y: float, sigma: float = 8.0) -> Tuple[float, float]:
        """对点击坐标注入高斯噪声。"""
        nx = self.rng.normal(loc=x, scale=sigma)
        ny = self.rng.normal(loc=y, scale=sigma)
        return (round(nx, 1), round(ny, 1))

    async def human_click(self, page, selector: str, sigma: float = 8.0) -> None:
        """在页面元素上执行人类风格点击。"""
        try:
            box = await page.locator(selector).bounding_box()
            if box is None:
                return
            cx = box["x"] + box["width"]  / 2
            cy = box["y"] + box["height"] / 2
            nx, ny = self.add_click_noise(cx, cy, sigma=sigma)
            await page.mouse.click(nx, ny)
        except Exception:
            await page.locator(selector).click()

    # ── 滚动速度曲线（非线性减速）────────────────────────────
    def generate_scroll_curve(self, start_y: int, end_y: int, num_steps: int = 30) -> List[int]:
        """生成非线性滚动轨迹（余弦加速曲线）。"""
        scroll_range = end_y - start_y
        curve = []
        for i in range(num_steps + 1):
            t = i / num_steps
            ease = (1 - math.cos(math.pi * t)) / 2
            y = start_y + int(scroll_range * ease)
            curve.append(y)
        jitter = self.rng.integers(-3, 3, size=len(curve))
        curve = [max(start_y, min(end_y, y + jitter[i])) for i, y in enumerate(curve)]
        return curve

    async def human_scroll(
        self,
        page,
        start_y: int = 0,
        end_y: int = 800,
        num_steps: int = 30,
        step_delay_ms: float = 20.0,
    ) -> None:
        """执行人类风格滚动。"""
        curve = self.generate_scroll_curve(start_y, end_y, num_steps)
        for y in curve:
            await page.evaluate(f"window.scrollTo(0, {y})")
            delay_jitter = self.rng.uniform(0.7, 1.3)
            await asyncio.sleep((step_delay_ms * delay_jitter) / 1000)

    # ── 组合：完整页面浏览行为序列 ───────────────────────────
    async def human_page_browse(
        self,
        page,
        target_selectors: List[str],
        think_before: bool = True,
    ) -> None:
        """执行完整人类页面浏览序列。"""
        if think_before:
            await self.async_delay("think")

        for sel in target_selectors:
            try:
                box = await page.locator(sel).bounding_box()
                if box is None:
                    continue
                cx = box["x"] + box["width"]  / 2
                cy = box["y"] + box["height"] / 2
                await self.human_mouse_move(
                    page,
                    start=(int(cx) - 50, int(cy) - 50),
                    end=(int(cx), int(cy)),
                    duration_ms=600.0,
                )
                await self.async_delay("hover")
                await self.human_click(page, sel, sigma=8.0)
                await self.async_delay("page_turn")
            except Exception:
                await page.locator(sel).click()
                await self.async_delay("page_turn")


# ─────────────────────────────────────────────────────────────
# AdaptiveLearningEngine
# ─────────────────────────────────────────────────────────────


class AdaptiveLearningEngine:
    """
    自适应学习引擎。

    三大功能：
    1. 行为结果记录：记录每种行为组合的成功/失败
    2. 模式挖掘：从历史数据中发现"高成功率"行为模式
    3. 动态调参：根据实时反馈自动调整行为参数

    数据存储在内存（deque）+ 可选 JSON 持久化。
    """

    @dataclass
    class BehaviorFingerprint:
        """描述一次采集请求的行为特征向量."""
        delay_mean_ms:   float
        delay_sigma_ms:  float
        mouse_speed:     float
        click_noise_px:  float
        scroll_steps:     int
        fingerprint_id:   str
        tls_pattern:      str
        doh_provider:     str

        def to_dict(self) -> dict:
            return asdict(self)

        @classmethod
        def from_dict(cls, d: dict) -> "AdaptiveLearningEngine.BehaviorFingerprint":
            return cls(**d)

    @dataclass
    class BehaviorResult:
        timestamp:     datetime
        fingerprint:   "AdaptiveLearningEngine.BehaviorFingerprint"
        source:        str
        http_status:   int
        success:       bool
        latency_ms:    float
        ban_detected:  bool
        captcha_seen:  bool

        def to_dict(self) -> dict:
            d = asdict(self)
            d["timestamp"] = self.timestamp.isoformat()
            return d

    def __init__(self, max_history: int = 10_000, seed: Optional[int] = None):
        self.rng = np.random.default_rng(seed)
        self.max_history = max_history
        self.results: deque = deque(maxlen=max_history)
        self._source_success: Dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        self._best_patterns: Dict[str, List[AdaptiveLearningEngine.BehaviorFingerprint]] = defaultdict(list)

        self._live_params: Dict[str, Any] = {
            "delay_mean_ms":   2000.0,
            "delay_sigma_ms":  800.0,
            "click_noise_px":  8.0,
            "mouse_speed_px_per_s": 200.0,
            "scroll_steps":    30,
            "doh_provider":    "cloudflare",
        }

        self._ban_rolling: deque = deque(maxlen=100)
        self._total_requests = 0

    def record(
        self,
        fingerprint: BehaviorFingerprint,
        source: str,
        http_status: int,
        success: bool,
        latency_ms: float,
        ban_detected: bool = False,
        captcha_seen: bool = False,
    ) -> None:
        """记录一次行为的结果。"""
        result = self.BehaviorResult(
            timestamp   = datetime.now(),
            fingerprint = fingerprint,
            source      = source,
            http_status = http_status,
            success     = success,
            latency_ms  = latency_ms,
            ban_detected= ban_detected,
            captcha_seen= captcha_seen,
        )
        self.results.append(result)
        self._source_success[source].append(success)
        self._total_requests += 1
        self._ban_rolling.append(ban_detected)
        self._adapt_live_params(source)

    def _adapt_live_params(self, source: str) -> None:
        """根据最近行为结果动态调整参数。"""
        recent = list(self.results)[-50:]
        if len(recent) < 10:
            return

        recent_bans = sum(1 for r in recent if r.ban_detected)
        recent_success_rate = sum(1 for r in recent if r.success) / len(recent)

        if recent_bans > 3:
            self._live_params["delay_mean_ms"] = min(self._live_params["delay_mean_ms"] * 1.5, 15000.0)
            self._live_params["delay_sigma_ms"] = min(self._live_params["delay_sigma_ms"] * 1.3, 5000.0)
        elif recent_success_rate > 0.95 and self._live_params["delay_mean_ms"] > 1000:
            self._live_params["delay_mean_ms"] *= 0.9

        if any(r.captcha_seen for r in recent[-5:]):
            providers = ["google", "cloudflare", "quad9", "ali"]
            current = self._live_params["doh_provider"]
            alternatives = [p for p in providers if p != current]
            self._live_params["doh_provider"] = self.rng.choice(alternatives)

    def get_tuned_params(self, source: str) -> Dict[str, Any]:
        """返回针对特定 source 调优后的行为参数。"""
        source_recent = list(self._source_success.get(source, []))
        success_rate = sum(source_recent) / len(source_recent) if source_recent else 0.85
        return {
            **self._live_params,
            "source_success_rate": round(success_rate, 3),
            "global_ban_rate": round(sum(self._ban_rolling) / max(len(self._ban_rolling), 1), 3),
            "total_requests": self._total_requests,
        }

    def recommend_behavior_config(self, source: str) -> Dict[str, Any]:
        """综合历史数据，推荐当前最优行为配置。"""
        params = self.get_tuned_params(source)
        ban_rate = params["global_ban_rate"]

        if ban_rate > 0.3:
            config = {
                "delay_mean_ms": params["delay_mean_ms"] * 2.0,
                "click_noise_px": 15.0,
                "mouse_speed_px_per_s": 120.0,
                "scroll_steps": 50,
                "strategy": "stealth",
            }
        elif ban_rate > 0.1:
            config = {
                "delay_mean_ms": params["delay_mean_ms"] * 1.3,
                "click_noise_px": 10.0,
                "mouse_speed_px_per_s": 180.0,
                "scroll_steps": 35,
                "strategy": "moderate",
            }
        else:
            config = {
                "delay_mean_ms": params["delay_mean_ms"],
                "click_noise_px": 8.0,
                "mouse_speed_px_per_s": 200.0,
                "scroll_steps": 30,
                "strategy": "normal",
            }
        return {**params, **config}

    def export(self, path: str) -> None:
        """导出历史记录到 JSON 文件。"""
        data = {
            "live_params": self._live_params,
            "results": [r.to_dict() for r in self.results],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def import_data(self, path: str) -> None:
        """从 JSON 文件导入历史记录。"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._live_params = data.get("live_params", self._live_params)
        for r in data.get("results", []):
            r["timestamp"] = datetime.fromisoformat(r["timestamp"])
            r["fingerprint"] = self.BehaviorFingerprint.from_dict(r["fingerprint"])
            self.results.append(self.BehaviorResult(**r))

    def health_metrics(self) -> Dict[str, Any]:
        """返回当前反检测系统健康度指标。"""
        recent = list(self.results)[-100:] if self.results else []
        total  = len(recent)
        return {
            "total_requests":       self._total_requests,
            "recent_success_rate":  sum(1 for r in recent if r.success) / total if total else 0.0,
            "recent_ban_rate":      sum(1 for r in recent if r.ban_detected) / total if total else 0.0,
            "recent_captcha_rate":  sum(1 for r in recent if r.captcha_seen) / total if total else 0.0,
            "live_delay_ms":        round(self._live_params["delay_mean_ms"], 1),
            "live_doh_provider":    self._live_params["doh_provider"],
            "strategy":            self.recommend_behavior_config("global").get("strategy", "unknown"),
        }
