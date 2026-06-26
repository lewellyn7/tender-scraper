"""Web 管理界面服务器"""
import asyncio
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
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import routes_n8n, routes_users
from app.api.routes.system import router as system_router
from app.core.safety_guard import check_production_safety
from app.api.metrics import router as metrics_router
from app.api.routes import api_router
from app.api.routes.document_upload import router as document_upload_router
from app.api.routes.pages import router as pages_router
# CSRFProtectionMiddleware: re-enabled after H-2 fix
from app.middleware.csrf import CSRFProtectionMiddleware
from app.api.metrics import PrometheusMiddleware
from app.middleware.security import (
    HTTPSForceMiddleware,
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from fastapi.middleware.cors import CORSMiddleware

# 日志配置
logger.remove()
logger.add(sys.stderr, level=LOG_LEVEL)

# 创建 FastAPI 应用
app = FastAPI(title="招投标采集系统", version="3.1")


@app.on_event("startup")
async def _warmup_embedding_model():
    """服务启动时预热 embedding 模型，避免首次请求 10s+ 延迟"""
    import threading

    def _load():
        try:
            from app.services.vector_store import get_embedding_model
            model = get_embedding_model()
            if model is not None:
                logger.info(f"[startup] embedding 模型预热完成: {type(model).__name__}")
            else:
                logger.warning("[startup] embedding 模型未加载（sentence-transformers 未安装，将使用 OpenAI fallback）")
        except Exception as e:
            logger.warning(f"[startup] embedding 模型预热失败: {e}")

    # 后台线程加载，不阻塞服务启动
    t = threading.Thread(target=_load, daemon=True)
    t.start()

    # 自用模式：初始化 admin 用户
    try:
        from app.config.settings import get_settings
        settings = get_settings()
        if settings.is_self_mode:
            _init_self_mode_admin()
    except Exception as e:
        logger.warning(f"[startup] 自用模式 admin 用户初始化失败: {e}")

    # 2026-06-26: PR feat/data-cache-v2 - 启动 DataCache Pub/Sub 订阅 + 预热
    try:
        from app.core.harvest.data_cache import data_cache
        await data_cache.start_pubsub_listener()
        # 30s 后异步预热 (不等预热完成, 启动不阻塞)
        asyncio.create_task(data_cache.warm_up())
        logger.info("[startup] DataCache Pub/Sub 订阅 + 预热已调度")
    except Exception as e:
        logger.warning(f"[startup] DataCache 启动失败: {e}")


def _init_self_mode_admin():
    """自用模式：确保 admin 用户存在"""
    try:
        from app.database import get_db
        from app.utils.security import hash_password
        from app.config.settings import get_settings
        import secrets

        settings = get_settings()
        db = get_db()
        existing = db.get_user_by_username(settings.default_admin_username)
        if existing:
            logger.info("[startup] 自用模式：admin 用户已存在")
            return

        # 创建 admin 用户
        pwd_hash, salt = hash_password(settings.default_admin_password)
        user_id = "admin_self_mode"
        db.create_user({
            "user_id": user_id,
            "username": settings.default_admin_username,
            "password_hash": pwd_hash,
            "password_salt": salt,
            "display_name": settings.default_admin_display_name,
            "role": "admin",
        })
        logger.info(f"[startup] 自用模式：admin 用户创建成功 (password={settings.default_admin_password})")
    except Exception as e:
        logger.error(f"[startup] 自用模式 admin 用户创建失败: {e}")


@app.on_event("shutdown")
async def _shutdown_data_cache():
    """2026-06-26: PR feat/data-cache-v2 - 优雅停 DataCache Pub/Sub."""
    try:
        from app.core.harvest.data_cache import data_cache
        await data_cache.stop_pubsub_listener()
        logger.info("[shutdown] DataCache Pub/Sub 已停止")
    except Exception as e:
        logger.warning(f"[shutdown] DataCache 停止失败: {e}")


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

# 添加安全中间件（按注册顺序：HTTPSForce → SecurityHeaders → RequestLogging → Prometheus）
app.add_middleware(HTTPSForceMiddleware)
app.add_middleware(RateLimitMiddleware, max_per_minute_guest=300, max_per_minute_user=1000)  # 2026-06-05 P0-8
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(PrometheusMiddleware)
app.add_middleware(CSRFProtectionMiddleware)  # H-2 fix: now validates session+token for mutation ops
# CORS: 允许前端开发服务器访问 API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # 前端开发服务器
        "http://localhost:5174",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(api_router)
app.include_router(routes_n8n.router)
app.include_router(routes_users.router)
app.include_router(document_upload_router)
app.include_router(pages_router)
app.include_router(metrics_router)
app.include_router(system_router)

# 静态文件
STATIC_DIR = Path(__file__).parent / "app" / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── SPA 单页应用（前后端分离）───────────────────────────────
SPA_DIR = Path(__file__).parent / "app" / "templates" / "spa"

@app.get("/spa")
async def serve_spa():
    """SPA 入口页 — 前端独立构建产物"""
    return FileResponse(str(SPA_DIR / "index.html"))

@app.get("/spa/assets/{path:path}")
async def serve_spa_assets(path: str):
    """SPA 静态资源（JS/CSS/图片）"""
    return FileResponse(str(SPA_DIR / "assets" / path))

# ── 健康检查 & 指标端点 ──────────────────────────────────
@app.get("/health")
async def health_check():
    """健康检查（包含向量库状态）"""
    from app.services.vector_store import get_vector_store
    try:
        vs = get_vector_store()
        stats = vs.stats()
    except Exception:
        stats = {"error": "vector store unavailable"}
    return {"status": "ok", "service": "tender-scraper", "vector": stats}

# Prometheus 指标端点 — 统一入口，同时服务标准 process/http 指标和自定义资质/日志指标
# make_asgi_app() 已移除：它会拦截 /metrics/* 子路径，导致 /metrics/qualifications 等路由失效
# /metrics 和 /metrics/* 子路由现在全部由 FastAPI 自身处理（见上方 app.include_router）

if __name__ == "__main__":
    # P0-3: production 环境 startup 安全断言 (defense-in-depth)
    check_production_safety()
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", 9099)))
