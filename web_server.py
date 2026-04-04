"""Web 管理界面服务器"""
from pathlib import Path
from loguru import logger
import sys
import os

# 日志级别配置
ENV = os.getenv("ENV", "development")
LOG_LEVEL = "DEBUG" if ENV == "development" else "INFO"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from app.api.routes import api_router
from app.api import routes_n8n, routes_users
from app.middleware.security import SecurityHeadersMiddleware, RequestLoggingMiddleware, RateLimitMiddleware
from app.middleware.csrf import CSRFProtectionMiddleware
import uvicorn

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
app.add_middleware(RateLimitMiddleware, max_per_minute=100)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(CSRFProtectionMiddleware)

# 注册路由
app.include_router(api_router)
app.include_router(routes_n8n.router)
app.include_router(routes_users.router)

# 静态文件
STATIC_DIR = Path(__file__).parent / "app" / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if __name__ == "__main__":
    print("🚀 启动 Web 管理界面: http://localhost:9000")
    uvicorn.run(app, host="0.0.0.0", port=9099)
