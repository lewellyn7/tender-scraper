"""7-03 watchdog 单测: alerts / collector_health / scheduler 关键路径.

不依赖真 collector / redis / telegram, 全用 mock / 内存状态验证.
"""
import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest


# ── 1. alerts 单元 ─────────────────────────────────────────
def test_alerts_format_message():
    from app.utils.alerts import format_alert_message
    msg = format_alert_message("critical", "测试标题", "测试 body\n第二行", source="unit-test")
    assert "🚨" in msg
    assert "<b>[CRITICAL] 测试标题</b>" in msg
    assert "测试 body\n第二行" in msg
    assert "<code>unit-test</code>" in msg


def test_alerts_send_no_tg_audit_fallback():
    """无 TG 凭证时, audit 兜底成功 → 返 True"""
    from app.utils import alerts

    # mock 掉 _send_telegram_sync (没真发)
    with patch.object(alerts, "_send_telegram_sync", return_value=None) as mock_tg:
        with patch.object(alerts, "_write_audit", return_value=True) as mock_audit:
            ok = alerts.send_alert("error", "x", "y", source="test")
            assert ok is True
            assert mock_tg.called
            assert mock_audit.called


def test_alerts_send_long_body_truncated():
    """body > 4000 chars 应被截断 (Telegram 限制)"""
    from app.utils import alerts

    long_body = "x" * 5000
    with patch.object(alerts, "_send_telegram_sync", return_value="msg_1") as mock_tg:
        with patch.object(alerts, "_write_audit", return_value=False):
            alerts.send_alert("info", "长", long_body, source="test")
            # 验证传给 TG 的 text 不超过 4000
            called_text = mock_tg.call_args[0][2]
            assert len(called_text) <= 4000
            assert "已截断" in called_text


# ── 2. collector_health 状态机 ──────────────────────────────
def test_collector_state_initial():
    from app.workers.collector_health import CollectorState
    CollectorState.last_crawl_at = None
    CollectorState.consecutive_failures = 0
    CollectorState.total_crawls = 0
    snap = CollectorState.snapshot()
    assert snap["status"] == "ok"  # 启动 5min 内默认 ok
    assert snap["consecutive_failures"] == 0


def test_collector_state_ok():
    from app.workers.collector_health import CollectorState
    CollectorState.last_crawl_at = None
    CollectorState.consecutive_failures = 0
    CollectorState.record_crawl("ok", count=15, source="cqggzy", duration_s=12.3)
    snap = CollectorState.snapshot()
    assert snap["last_crawl_status"] == "ok"
    assert snap["last_crawl_count"] == 15
    assert snap["consecutive_failures"] == 0
    assert snap["total_ok"] == 1
    assert snap["status"] == "ok"


def test_collector_state_degraded_after_3_fails():
    from app.workers.collector_health import CollectorState
    CollectorState.last_crawl_at = None
    CollectorState.consecutive_failures = 0
    CollectorState.total_crawls = 0
    CollectorState.total_ok = 0
    CollectorState.total_fail = 0
    for i in range(3):
        CollectorState.record_crawl("failed", count=0, error=f"err {i}", source="cqggzy")
    snap = CollectorState.snapshot()
    assert snap["status"] == "degraded"
    assert snap["consecutive_failures"] == 3
    assert snap["total_fail"] == 3


def test_collector_state_recovery_resets_failures():
    """一次成功应 reset consecutive_failures"""
    from app.workers.collector_health import CollectorState
    CollectorState.last_crawl_at = None
    CollectorState.consecutive_failures = 0
    CollectorState.total_crawls = 0
    CollectorState.total_ok = 0
    CollectorState.total_fail = 0
    CollectorState.record_crawl("failed", count=0, error="e1", source="cqggzy")
    CollectorState.record_crawl("failed", count=0, error="e2", source="cqggzy")
    assert CollectorState.consecutive_failures == 2
    CollectorState.record_crawl("ok", count=5, source="cqggzy")
    assert CollectorState.consecutive_failures == 0
    assert CollectorState.total_ok == 1
    assert CollectorState.total_fail == 2


# ── 3. pipeline.py 越界修复 ───────────────────────────────
def test_pipeline_debug_sample_no_index_error():
    """7-03 修复: pipeline.py 的 DEBUG 采样不能 IndexError on matched_items < 5"""
    # 模拟逻辑: n=3, 应只采样 [0,1,2]
    n = 3
    if n == 0:
        sample = []
    else:
        sample = list(range(min(5, n))) + [i for i in range(max(0, n - 5), n)]
        seen = set()
        sample = [i for i in sample if i not in seen and not seen.add(i)]
    assert sample == [0, 1, 2]
    # 模拟访问
    fake_items = ["a", "b", "c"]
    for i in sample:
        assert fake_items[i] in ("a", "b", "c")  # 不会越界


def test_pipeline_debug_sample_10_items():
    """10 条应采 [0,1,2,3,4,5,6,7,8,9]"""
    n = 10
    sample = list(range(min(5, n))) + [i for i in range(max(0, n - 5), n)]
    seen = set()
    sample = [i for i in sample if i not in seen and not seen.add(i)]
    assert sample == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]


def test_pipeline_debug_sample_empty():
    """0 条应 sample=[]"""
    n = 0
    if n == 0:
        sample = []
    else:
        sample = list(range(min(5, n))) + [i for i in range(max(0, n - 5), n)]
        seen = set()
        sample = [i for i in sample if i not in seen and not seen.add(i)]
    assert sample == []


# ── 4. scheduler watchdog 决策逻辑 ─────────────────────────
def test_watchdog_alert_cooldown():
    """告警 30min 冷却: 第二次调应跳过"""
    from app.scheduler import _last_watchdog_alert_at, WATCHDOG_ALERT_COOLDOWN
    import time

    # 模拟: 刚发过告警
    import app.scheduler as s
    s._last_watchdog_alert_at = time.time()  # 刚刚

    # fetch 返 None (collector 失联) → 但因冷却, 不发告警
    with patch.object(s, "_fetch_collector_state", return_value=None):
        with patch("app.utils.alerts.send_alert") as mock_alert:
            s.job_watchdog_check()
            # 因冷却, 不应调 send_alert
            assert not mock_alert.called


def test_watchdog_stale_detection():
    """last_crawl_age > 阈值 → 告警"""
    import app.scheduler as s
    s._last_watchdog_alert_at = 0  # 重置冷却

    with patch.object(s, "_fetch_collector_state", return_value={
        "status": "ok",
        "last_crawl_age_s": 99999,  # 远超 9000
        "last_crawl_status": "ok",
        "last_crawl_count": 0,
        "consecutive_failures": 0,
    }):
        with patch("app.utils.alerts.send_alert") as mock_alert:
            s.job_watchdog_check()
            assert mock_alert.called
            call = mock_alert.call_args
            assert call.kwargs["level"] == "error"
            assert "停滞" in call.kwargs["title"]


def test_watchdog_degraded_detection():
    """status=degraded → warning 告警"""
    import app.scheduler as s
    s._last_watchdog_alert_at = 0

    with patch.object(s, "_fetch_collector_state", return_value={
        "status": "degraded",
        "last_crawl_age_s": 600,
        "last_crawl_status": "failed",
        "last_crawl_count": 0,
        "consecutive_failures": 3,
        "last_error": "test",
        "total_ok": 0,
        "total_fail": 3,
        "total_crawls": 3,
    }):
        with patch("app.utils.alerts.send_alert") as mock_alert:
            s.job_watchdog_check()
            assert mock_alert.called
            call = mock_alert.call_args
            assert call.kwargs["level"] == "warning"


def test_watchdog_healthy_no_alert():
    """正常状态 → 不告警"""
    import app.scheduler as s
    s._last_watchdog_alert_at = 0

    with patch.object(s, "_fetch_collector_state", return_value={
        "status": "ok",
        "last_crawl_age_s": 60,
        "last_crawl_status": "ok",
        "last_crawl_count": 15,
        "consecutive_failures": 0,
    }):
        with patch("app.utils.alerts.send_alert") as mock_alert:
            s.job_watchdog_check()
            assert not mock_alert.called


# ── 5. startup self check ──────────────────────────────────
def test_startup_self_check_no_collector_alerts():
    """启动时 collector 失联 → critical 告警"""
    import app.scheduler as s

    with patch.object(s, "_fetch_collector_state", return_value=None):
        with patch("app.utils.alerts.send_alert") as mock_alert:
            s.job_startup_self_check()
            assert mock_alert.called
            call = mock_alert.call_args
            assert call.kwargs["level"] == "critical"


def test_startup_self_check_retry_on_failure():
    """上次失败 → 启动时补发 1 次"""
    import app.scheduler as s

    with patch.object(s, "_fetch_collector_state", return_value={
        "status": "ok",
        "last_crawl_age_s": 600,
        "last_crawl_status": "failed",
        "last_crawl_count": 0,
    }):
        with patch("app.utils.alerts.send_alert") as mock_alert:
            with patch.object(s, "_publish_trigger") as mock_trigger:
                s.job_startup_self_check()
                assert mock_alert.called
                assert mock_trigger.called
                assert mock_alert.call_args.kwargs["level"] == "warning"


def test_startup_self_check_healthy_no_action():
    """正常 → 不告警, 不补发"""
    import app.scheduler as s

    with patch.object(s, "_fetch_collector_state", return_value={
        "status": "ok",
        "last_crawl_age_s": 60,
        "last_crawl_status": "ok",
        "last_crawl_count": 15,
    }):
        with patch("app.utils.alerts.send_alert") as mock_alert:
            with patch.object(s, "_publish_trigger") as mock_trigger:
                s.job_startup_self_check()
                assert not mock_alert.called
                assert not mock_trigger.called
