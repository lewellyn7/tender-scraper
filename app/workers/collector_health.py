"""P1-2: Collector Health Probe — stdlib HTTP server (轻量, 零依赖)

提供 /health 端点供 docker healthcheck / Prometheus 探测使用。
运行在独立线程,不阻塞 CollectorWorker 主循环。

端点:
- GET /health       → JSON { status, service, last_crawl, uptime_s }
- GET /health/live  → 200 OK (liveness, 进程在跑)
- GET /health/ready → 200 OK (readiness, 可以接采集任务)

设计:
- 用 stdlib http.server (无 aiohttp 依赖, 减少 collector 启动开销)
- 端口默认 8001 (web 是 9099, 不冲突)
- 状态信息存在 CollectorState 模块级变量, collector 主动更新
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
    """Collector 运行时状态,供 health server 读取"""

    started_at: float = time.time()
    last_crawl_at: Optional[float] = None
    last_crawl_status: Optional[str] = None  # "ok" | "fail" | None
    last_crawl_count: Optional[int] = None
    last_error: Optional[str] = None

    @classmethod
    def record_crawl(cls, status: str, count: int = 0, error: Optional[str] = None) -> None:
        cls.last_crawl_at = time.time()
        cls.last_crawl_status = status
        cls.last_crawl_count = count
        cls.last_error = error

    @classmethod
    def snapshot(cls) -> Dict[str, Any]:
        uptime = time.time() - cls.started_at
        snap: Dict[str, Any] = {
            "status": "ok",
            "service": "tender-scraper-collector",
            "uptime_s": round(uptime, 1),
            "last_crawl_at": (
                time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(cls.last_crawl_at))
                if cls.last_crawl_at
                else None
            ),
            "last_crawl_status": cls.last_crawl_status,
            "last_crawl_count": cls.last_crawl_count,
            "last_error": cls.last_error,
        }
        # 简单健康判定: 启动 5 分钟内无 last_crawl_at → 仍 "ok" (可能还没触发)
        # 启动 5 分钟后无 last_crawl_at → 标 "idle"
        if cls.last_crawl_at is None and uptime > 300:
            snap["status"] = "idle"
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
