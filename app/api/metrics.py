"""
统一 Prometheus 指标端点 + 中间件

暴露端点:
    GET /metrics       — 标准 + 资质 + 日志聚合（Prometheus 主抓入口）
    GET /metrics/qualifications — 仅资质指标（调试用）
    GET /metrics/logs        — 仅日志聚合（调试用）
    GET /metrics/standard    — 仅标准 process/http 指标（调试用）

在 FastAPI 应用中注册中间件:
    from app.api.metrics import PrometheusMiddleware
    app.add_middleware(PrometheusMiddleware)

    from app.api.metrics import router as metrics_router
    app.include_router(metrics_router)
"""

import re
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from fastapi import APIRouter, Response as FastAPIResponse

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter as PCounter,
    Gauge,
    Histogram,
    generate_latest,
    REGISTRY,
)

from app.database import get_db

router = APIRouter(prefix="/metrics", tags=["监控指标"])

# ── HTTP 请求指标 ─────────────────────────────────────────

HTTP_REQUESTS_TOTAL = PCounter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    """记录 HTTP 请求计数和延迟"""

    async def dispatch(self, request: Request, call_next):
        # 跳过 /metrics 自身避免递归
        if request.url.path.startswith("/metrics"):
            return await call_next(request)

        method = request.method
        # 归一化 endpoint：替换路径参数为 placeholder
        path = request.url.path
        path = re.sub(r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '/{id}', path)
        path = re.sub(r'/\d+', '/{id}', path)

        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        HTTP_REQUESTS_TOTAL.labels(
            method=method,
            endpoint=path,
            status_code=response.status_code,
        ).inc()

        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=method,
            endpoint=path,
        ).observe(duration)

        return response


# ── 采集指标 ─────────────────────────────────────────────

HARVEST_TASKS_TOTAL = PCounter(
    "harvest_tasks_total",
    "Total harvest tasks",
    ["source", "status"],
    registry=REGISTRY,
)

HARVEST_TASK_DURATION_SECONDS = Histogram(
    "harvest_task_duration_seconds",
    "Harvest task duration in seconds",
    ["source"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
    registry=REGISTRY,
)

HARVEST_ITEMS_COLLECTED = PCounter(
    "harvest_items_collected_total",
    "Total items collected",
    ["source"],
    registry=REGISTRY,
)

ACTIVE_CRAWLERS = Gauge(
    "active_crawlers",
    "Number of currently active crawlers",
    ["source"],
    registry=REGISTRY,
)

# ── 资质指标 ─────────────────────────────────────────────

QUALIFICATION_GAUGE = Gauge(
    "qualification_days_until_expiry",
    "距离资质过期的天数（负数=已过期）",
    ["qualification_name", "certificate_no", "category", "level", "issuer", "status"],
    registry=REGISTRY,
)

QUALIFICATION_TOTAL = Gauge(
    "qualification_total",
    "资质总数（按分类+状态）",
    ["category", "status"],
    registry=REGISTRY,
)

QUALIFICATION_EXPIRED_COUNT = Gauge(
    "qualification_expired_count",
    "已过期资质数量",
    [],
    registry=REGISTRY,
)

QUALIFICATION_EXPIRING_7D = Gauge(
    "qualification_expiring_7d_count",
    "7天内到期资质数量",
    [],
    registry=REGISTRY,
)

QUALIFICATION_EXPIRING_30D = Gauge(
    "qualification_expiring_30d_count",
    "30天内到期资质数量",
    [],
    registry=REGISTRY,
)

# ── 日志聚合指标 ─────────────────────────────────────────

LOG_LEVEL_COUNTER = PCounter(
    "log_messages_total",
    "日志行总数（按级别）",
    ["level", "source"],
    registry=REGISTRY,
)

LOG_ERROR_RATE = Gauge(
    "log_error_rate_5m",
    "最近 5 分钟各级别日志条数",
    ["level", "source"],
    registry=REGISTRY,
)

LOG_FILE_PATTERNS = {
    "scraper": re.compile(
        r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,\.]\d+)\s+\|\s+(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+\|(?P<msg>.*)$",
        re.IGNORECASE,
    ),
}

LOG_DIR = Path("/app/logs")


def _refresh_qualification_metrics():
    """从数据库拉取资质数据，刷新 Prometheus 指标"""
    db = get_db()
    try:
        items, _ = db.get_qualifications(page=1, page_size=10000)
    except Exception:
        return

    today = date.today()

    QUALIFICATION_GAUGE._metrics.clear()
    expired_count = 0
    expiring_7d = 0
    expiring_30d = 0
    category_status: dict = {}

    for item in items:
        cert_no = item.get("certificate_no", "") or "N/A"
        name = item.get("name", "未知") or "未知"
        category = item.get("category", "其他") or "其他"
        level = item.get("level", "") or ""
        issuer = item.get("issuer", "") or ""
        status = item.get("status", "有效") or "有效"

        days: Optional[int] = None
        if item.get("valid_to"):
            try:
                valid_to = date.fromisoformat(str(item["valid_to"]))
                days = (valid_to - today).days
            except (ValueError, TypeError):
                pass

        if days is not None:
            QUALIFICATION_GAUGE.labels(
                qualification_name=name,
                certificate_no=cert_no,
                category=category,
                level=level,
                issuer=issuer,
                status=status,
            ).set(days)

        key = (category, status)
        category_status[key] = category_status.get(key, 0) + 1

        if days is not None:
            if days < 0:
                expired_count += 1
            elif days <= 7:
                expiring_7d += 1
                expiring_30d += 1
            elif days <= 30:
                expiring_30d += 1

    for (cat, stat), cnt in category_status.items():
        QUALIFICATION_TOTAL.labels(category=cat, status=stat).set(cnt)

    QUALIFICATION_EXPIRED_COUNT.set(expired_count)
    QUALIFICATION_EXPIRING_7D.set(expiring_7d)
    QUALIFICATION_EXPIRING_30D.set(expiring_30d)


def _refresh_log_metrics():
    """解析日志文件，刷新日志聚合指标"""
    for src, pattern in LOG_FILE_PATTERNS.items():
        log_file = LOG_DIR / f"{src}.log"
        if not log_file.exists():
            log_file = LOG_DIR / "scraper.log"
        if not log_file.exists():
            continue

        cutoff = datetime.now() - timedelta(minutes=5)
        counts: Counter = Counter()

        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as fh:
                for line in reversed(fh.readlines()[-10000:]):
                    m = pattern.match(line.strip())
                    if not m:
                        continue
                    try:
                        ts_str = m.group("ts").replace(",", ".")
                        ts = datetime.fromisoformat(ts_str)
                    except (ValueError, OSError):
                        continue
                    if ts < cutoff:
                        break
                    counts[m.group("level").upper()] += 1
        except Exception:
            pass

        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            cnt = counts.get(level, 0)
            LOG_LEVEL_COUNTER.labels(level=level, source=src)
            LOG_ERROR_RATE.labels(level=level, source=src).set(cnt)


def _refresh_all():
    """同时刷新所有自定义指标"""
    _refresh_qualification_metrics()
    _refresh_log_metrics()


# ── 端点定义 ─────────────────────────────────────────────

@router.get("")
async def all_metrics():
    """
    GET /metrics
    统一入口：标准 process/http 指标 + 资质 + 日志聚合
    Prometheus scrape 配置对应此端点
    """
    _refresh_all()
    return FastAPIResponse(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@router.get("/qualifications")
async def qualification_metrics():
    """GET /metrics/qualifications — 仅资质指标（调试用）"""
    _refresh_qualification_metrics()
    return FastAPIResponse(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@router.get("/logs")
async def log_metrics_endpoint():
    """GET /metrics/logs — 仅日志聚合指标（调试用）"""
    _refresh_log_metrics()
    return FastAPIResponse(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@router.get("/standard")
async def standard_metrics():
    """GET /metrics/standard — 仅标准 process/http 指标"""
    return FastAPIResponse(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
