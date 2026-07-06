"""P1-2: Collector Health Probe — stdlib HTTP server (轻量, 零依赖)

提供 /health 端点供 docker healthcheck / Prometheus 探测使用。
运行在独立线程,不阻塞 CollectorWorker 主循环。

端点:
- GET /health       → JSON { status, service, last_crawl, uptime_s, ... }
- GET /health/live  → 200 OK (liveness, 进程在跑)
- GET /health/ready → 200 OK (readiness, 可以接采集任务)
- GET /health/collector-state → 详细状态 (给 scheduler watchdog 用)

设计:
- 用 stdlib http.server (无 aiohttp 依赖, 减少 collector 启动开销)
- 端口默认 8001 (web 是 9099, 不冲突)
- 状态信息存在 CollectorState 模块级变量, collector 主动更新
- 7-03 扩展: 状态机 ok / failed / degraded, 累计指标
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional


# ── 模块级状态（collector 主动写入） ────────────────────────────
class CollectorState:
    """Collector 运行时状态,供 health server 读取

    7-03 扩展:
    - last_crawl_status: "ok" | "failed" | "degraded" (修复之前 "no result" 假阴性)
    - last_count: 本次采集数量
    - last_error: 错误消息
    - consecutive_failures: 连续失败次数 (watchdog 用)
    - total_crawls / total_ok / total_fail: 生命周期累计
    - last_alert_at: 上次告警时间 (避免频繁告警)
    """

    started_at: float = time.time()
    last_crawl_at: Optional[float] = None
    last_crawl_status: Optional[str] = None  # "ok" | "failed" | "degraded" | None
    last_crawl_count: Optional[int] = None
    last_error: Optional[str] = None

    # 7-03 新增
    last_crawl_source: Optional[str] = None  # "cqggzy" / "fahcqmu" / "manual"
    last_crawl_duration_s: Optional[float] = None
    consecutive_failures: int = 0
    total_crawls: int = 0
    total_ok: int = 0
    total_fail: int = 0
    last_alert_at: Optional[float] = None  # 上次告警时间戳 (避免重复)

    @classmethod
    def record_crawl(
        cls,
        status: str,
        count: int = 0,
        error: Optional[str] = None,
        source: Optional[str] = None,
        duration_s: Optional[float] = None,
    ) -> None:
        """记录一次采集结果.

        Args:
            status: "ok" (count > 0 成功) | "failed" (异常/崩溃) | "degraded" (完成但 0 条)
            count: 采集到的条数
            error: 错误消息
            source: "cqggzy" / "fahcqmu" / "manual"
            duration_s: 耗时
        """
        cls.last_crawl_at = time.time()
        cls.last_crawl_status = status
        cls.last_crawl_count = count
        cls.last_crawl_source = source
        cls.last_crawl_duration_s = round(duration_s, 1) if duration_s else None
        cls.last_error = error
        cls.total_crawls += 1

        if status == "ok":
            cls.total_ok += 1
            cls.consecutive_failures = 0
        else:
            cls.total_fail += 1
            cls.consecutive_failures += 1

    @classmethod
    def mark_alert_sent(cls) -> None:
        """记录告警已发 (供去重)"""
        cls.last_alert_at = time.time()

    @classmethod
    def snapshot(cls) -> Dict[str, Any]:
        uptime = time.time() - cls.started_at
        last_crawl_age = (time.time() - cls.last_crawl_at) if cls.last_crawl_at else None
        snap: Dict[str, Any] = {
            "status": "ok",
            "service": "tender-scraper-collector",
            "uptime_s": round(uptime, 1),
            "last_crawl_at": (
                time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(cls.last_crawl_at))
                if cls.last_crawl_at
                else None
            ),
            "last_crawl_age_s": round(last_crawl_age, 1) if last_crawl_age else None,
            "last_crawl_status": cls.last_crawl_status,
            "last_crawl_count": cls.last_crawl_count,
            "last_crawl_source": cls.last_crawl_source,
            "last_crawl_duration_s": cls.last_crawl_duration_s,
            "last_error": cls.last_error,
            "consecutive_failures": cls.consecutive_failures,
            "total_crawls": cls.total_crawls,
            "total_ok": cls.total_ok,
            "total_fail": cls.total_fail,
        }
        # 7-03 状态机: 三档
        if cls.last_crawl_at is None and uptime > 300:
            # 启动 5 分钟后还没采过 → idle (不是 failed, 可能是无 cron 周期)
            snap["status"] = "idle"
        elif cls.consecutive_failures >= 3:
            # 连续 3 次失败 → degraded
            snap["status"] = "degraded"
        elif cls.consecutive_failures > 0:
            # 1-2 次失败 → 仍 ok, 但 consecutive_failures > 0
            snap["status"] = "ok"
        return snap


# ── HTTP Handler ────────────────────────────────────────────
class _HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        """静音 access log (loguru 已经在管日志)"""
        pass

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health" or self.path == "/health/":
            self._send_json(200, CollectorState.snapshot())
        elif self.path == "/health/live":
            self._send_json(200, {"status": "alive"})
        elif self.path == "/health/ready":
            snap = CollectorState.snapshot()
            code = 200 if snap["status"] in ("ok", "idle") else 503
            self._send_json(code, snap)
        elif self.path == "/health/collector-state":
            # 7-03: 详细状态端点, scheduler watchdog 用
            self._send_json(200, CollectorState.snapshot())
        else:
            self._send_json(404, {"error": "not found", "path": self.path})


# ── 启动器 ──────────────────────────────────────────────
_health_server: Optional[ThreadingHTTPServer] = None
_health_thread: Optional[threading.Thread] = None


def start_health_server(host: str = "0.0.0.0", port: int = 8001) -> None:
    """P1-2: 启动 health server (独立线程, 阻塞 collector.start())

    Args:
        host: 监听地址, 默认 0.0.0.0
        port: 监听端口, 默认 8001 (避免与 web 9099 冲突)
    """
    global _health_server, _health_thread

    if _health_server is not None:
        return  # 已启动, 幂等

    _health_server = ThreadingHTTPServer((host, port), _HealthHandler)
    _health_thread = threading.Thread(
        target=_health_server.serve_forever,
        daemon=True,
        name="collector-health-server",
    )
    _health_thread.start()
    # 显式 stdout (docker logs 能看到)
    print(f"[Collector:health] health server listening on {host}:{port}", flush=True)


def stop_health_server() -> None:
    """停止 health server (测试用)"""
    global _health_server, _health_thread
    if _health_server is not None:
        _health_server.shutdown()
        _health_server.server_close()
        _health_server = None
        _health_thread = None
