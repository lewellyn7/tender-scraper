"""安全中间件"""

import time

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, RedirectResponse

from app.utils.security import SECURITY_HEADERS, generate_request_id
from config.settings import settings


class HTTPSForceMiddleware(BaseHTTPMiddleware):
    """生产环境强制 HTTPS 重定向"""

    async def dispatch(self, request: Request, call_next) -> Response:
        if not settings.FORCE_HTTPS:
            return await call_next(request)

        # 仅在 HTTP 请求时重定向（跳过 WebSocket、健康检查等）
        if request.url.scheme == "https":
            return await call_next(request)

        # 跳过内部路径
        if request.url.path in ("/health", "/metrics"):
            return await call_next(request)

        # 构造 HTTPS URL 并重定向
        https_url = request.url.replace(scheme="https")
        # 保留原始端口（若使用标准443则不需显式端口）
        return RedirectResponse(url=str(https_url), status_code=301)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """添加安全响应头"""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # 添加安全头
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value

        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """请求日志中间件"""

    async def dispatch(self, request: Request, call_next) -> Response:
        # 生成请求 ID
        request_id = generate_request_id()
        request.state.request_id = request_id

        start_time = time.time()

        # 记录请求
        logger.info(
            f"[{request_id}] {request.method} {request.url.path}"
            f" - Client: {request.client.host if request.client else 'unknown'}"
        )

        try:
            response = await call_next(request)

            # 计算处理时间
            process_time = time.time() - start_time

            # 添加响应头
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time"] = f"{process_time:.3f}s"

            # 记录响应
            logger.info(
                f"[{request_id}] {request.method} {request.url.path}"
                f" - Status: {response.status_code}"
                f" - Time: {process_time:.3f}s"
            )

            return response

        except Exception as e:
            process_time = time.time() - start_time
            logger.error(
                f"[{request_id}] {request.method} {request.url.path}"
                f" - Error: {str(e)}"
                f" - Time: {process_time:.3f}s"
            )
            raise


class RateLimitMiddleware(BaseHTTPMiddleware):
    """简单速率限制中间件
    
    - 未登录用户: 500次/分钟
    - 已登录用户: 1000次/分钟
    - 认证相关路径(/login, /register)完全绕过IP限流（自有装饰器保护）
    """

    # 认证路径 — 完全绕过IP限流（登录有独立per-user装饰器保护）
    _AUTH_PATHS = frozenset(["/login", "/register", "/api/users/login", "/api/users/register"])

    # 2026-06-05 P0-8: 健康检查/静态资源/监控端点不受限流
    _EXEMPT_PATH_PREFIXES = ("/health", "/metrics", "/spa/", "/static/", "/favicon")

    def __init__(self, app, max_per_minute_guest: int = 500, max_per_minute_user: int = 1000):
        super().__init__(app)
        self.max_per_minute_guest = max_per_minute_guest
        self.max_per_minute_user = max_per_minute_user
        self._requests = {}

    def _get_user_identifier(self, request: Request) -> str:
        """获取用户标识：优先用 session token，否则用 IP"""
        token = request.cookies.get("session_token") or request.headers.get("X-Session-Token")
        if token:
            return f"token:{token[:16]}"
        client_ip = request.client.host if request.client else "unknown"
        return f"ip:{client_ip}"

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # 认证路径 / 健康检查 / 静态资源 → 跳过IP限流
        if path in self._AUTH_PATHS or path.startswith("/api/users/"):
            return await call_next(request)
        if any(path.startswith(prefix) for prefix in self._EXEMPT_PATH_PREFIXES):
            return await call_next(request)

        identifier = self._get_user_identifier(request)
        current_minute = int(time.time() / 60)
        key = f"{identifier}:{current_minute}"

        # 清理旧记录
        cutoff_minute = current_minute - 1
        self._requests = {
            k: v for k, v in self._requests.items() if int(k.split(":")[-1]) >= cutoff_minute
        }

        # 区分登录状态
        is_guest = not (request.cookies.get("session_token") or request.headers.get("X-Session-Token"))
        limit = self.max_per_minute_guest if is_guest else self.max_per_minute_user

        # 检查限制
        if key in self._requests:
            count = self._requests[key]
            if count >= limit:
                return JSONResponse(status_code=429, content={"error": "请求过于频繁，请稍后再试"})
            self._requests[key] = count + 1
        else:
            self._requests[key] = 1

        return await call_next(request)
