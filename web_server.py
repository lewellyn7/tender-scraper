"""Web 管理界面服务器"""
import os
import sys
from pathlib import Path

from loguru import logger

# 日志级别配置
ENV = os.getenv("ENV", "development")
LOG_LEVEL = "DEBUG" if ENV == "development" else "INFO"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import routes_n8n, routes_users
from app.api.metrics import router as metrics_router
from app.api.routes import api_router
from app.api.routes.document_upload import router as document_upload_router
from app.api.routes.pages import router as pages_router
# CSRF disabled: API uses X-Session-Token header auth (no cookie-based sessions)
# from app.middleware.csrf import CSRFProtectionMiddleware
from app.api.metrics import PrometheusMiddleware
from app.middleware.security import (
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)

# 日志配置
logger.remove()
logger.add(sys.stderr, level=LOG_LEVEL)

# 创建 FastAPI 应用
app = FastAPI(title="招投标采集系统", version="3.1")

# 检测是否为生产模式
is_production = os.getenv("ENV", "development") == "production"

# 自定义异常处理器
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    if is_production:
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "detail": None}
        )
    else:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "type": type(exc).__name__}
        )

# 添加安全中间件
app.add_middleware(RateLimitMiddleware, max_per_minute_guest=200, max_per_minute_user=600)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(PrometheusMiddleware)
# app.add_middleware(CSRFProtectionMiddleware)  # disabled - breaks POST endpoints

# 注册路由
app.include_router(api_router)
app.include_router(routes_n8n.router)
app.include_router(routes_users.router)
app.include_router(document_upload_router)
app.include_router(pages_router)
app.include_router(metrics_router)

# 静态文件
STATIC_DIR = Path(__file__).parent / "app" / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── 健康检查 & 指标端点 ──────────────────────────────────
@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "tender-scraper"}

# Prometheus 指标端点 — 统一入口，同时服务标准 process/http 指标和自定义资质/日志指标
# make_asgi_app() 已移除：它会拦截 /metrics/* 子路径，导致 /metrics/qualifications 等路由失效
# /metrics 和 /metrics/* 子路由现在全部由 FastAPI 自身处理（见上方 app.include_router）

if __name__ == "__main__":
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", 9099)))
