"""P1-2 collector_health 单测

测试场景:
1. CollectorState.record_crawl / snapshot
2. /health 端点返回 200 + JSON
3. /health/live 返回 200
4. /health/ready 返回 200
5. 404 端点
6. 启动/停止幂等
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.workers.collector_health import (
    CollectorState,
    start_health_server,
    stop_health_server,
)


@pytest.fixture
def health_server():
    """启动 health server, 端口 18099 (避免冲突)"""
    CollectorState.started_at = time.time()
    CollectorState.last_crawl_at = None
    CollectorState.last_crawl_status = None
    CollectorState.last_crawl_count = None
    CollectorState.last_error = None

    start_health_server(host="127.0.0.1", port=18099)
    time.sleep(0.2)  # 等 server up
    yield "http://127.0.0.1:18099"
    stop_health_server()
    time.sleep(0.1)


def _get(url, timeout=2):
    """GET + 解析 JSON, 处理 4xx"""
    try:
        r = urllib.request.urlopen(url, timeout=timeout)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class TestCollectorState:
    """CollectorState 模块级状态"""

    def test_initial_snapshot(self):
        """初始 snapshot: status=ok, last_crawl=None"""
        CollectorState.started_at = time.time()
        CollectorState.last_crawl_at = None
        snap = CollectorState.snapshot()
        assert snap["status"] == "ok"
        assert snap["service"] == "tender-scraper-collector"
        assert snap["last_crawl_at"] is None
        assert snap["last_crawl_count"] is None

    def test_idle_after_5min(self, monkeypatch):
        """启动 5 分钟后无 last_crawl → status=idle"""
        # 模拟 6 分钟前启动
        CollectorState.started_at = time.time() - 360
        CollectorState.last_crawl_at = None
        snap = CollectorState.snapshot()
        assert snap["status"] == "idle"

    def test_record_crawl_updates_state(self):
        """record_crawl 写入 last_crawl_* 字段"""
        CollectorState.record_crawl("ok", count=42)
        assert CollectorState.last_crawl_status == "ok"
        assert CollectorState.last_crawl_count == 42
        assert CollectorState.last_crawl_at is not None
        snap = CollectorState.snapshot()
        assert snap["last_crawl_count"] == 42

    def test_record_crawl_with_error(self):
        """record_crawl 写入 error 信息"""
        CollectorState.record_crawl("fail", count=0, error="Connection refused")
        assert CollectorState.last_error == "Connection refused"
        assert CollectorState.last_crawl_status == "fail"


class TestHealthEndpoints:
    """/health, /health/live, /health/ready 端点"""

    def test_health_returns_200(self, health_server):
        """GET /health → 200 + JSON"""
        code, data = _get(f"{health_server}/health")
        assert code == 200
        assert data["status"] == "ok"
        assert data["service"] == "tender-scraper-collector"
        assert "uptime_s" in data

    def test_health_live_returns_200(self, health_server):
        """GET /health/live → 200 + alive"""
        code, data = _get(f"{health_server}/health/live")
        assert code == 200
        assert data["status"] == "alive"

    def test_health_ready_returns_200(self, health_server):
        """GET /health/ready → 200 (ok / idle 都视为 ready)"""
        code, data = _get(f"{health_server}/health/ready")
        assert code == 200
        assert data["status"] in ("ok", "idle")

    def test_health_reflects_record(self, health_server):
        """record_crawl 后 /health 应反映新状态"""
        CollectorState.record_crawl("ok", count=99)
        code, data = _get(f"{health_server}/health")
        assert code == 200
        assert data["last_crawl_count"] == 99
        assert data["last_crawl_status"] == "ok"
        assert data["last_crawl_at"] is not None

    def test_404_for_unknown_path(self, health_server):
        """未知路径 → 404"""
        code, data = _get(f"{health_server}/nonexistent")
        assert code == 404
        assert "error" in data


class TestStartStop:
    """启动/停止幂等性"""

    def test_start_idempotent(self):
        """多次 start 不应报错 (幂等)"""
        start_health_server(host="127.0.0.1", port=18100)
        time.sleep(0.1)
        start_health_server(host="127.0.0.1", port=18100)  # 第二次应静默
        time.sleep(0.1)
        stop_health_server()
        # 验证可以重启
        start_health_server(host="127.0.0.1", port=18100)
        time.sleep(0.1)
        stop_health_server()

    def test_stop_when_not_started(self):
        """未启动时 stop 不应报错"""
        stop_health_server()  # 不抛异常


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
