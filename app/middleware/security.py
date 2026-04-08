"""安全中间件"""

import time

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.utils.security import SECURITY_HEADERS, generate_request_id


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
    """简单速率限制中间件（已修复内存泄漏）"""

    def __init__(self, app, max_per_minute: int = 100):
        super().__init__(app)
        self.max_per_minute = max_per_minute
        self._requests = {}

    async def dispatch(self, request: Request, call_next) -> Response:
        # 获取客户端 IP
        client_ip = request.client.host if request.client else "unknown"
        current_minute = int(time.time() / 60)
        key = f"{client_ip}:{current_minute}"

        # 清理旧记录 (每次请求主动清理，避免内存泄漏)
        cutoff_minute = current_minute - 1  # 保留最近1分钟的记录
        self._requests = {
            k: v for k, v in self._requests.items() if int(k.split(":")[1]) >= cutoff_minute
        }

        # 检查限制
        if key in self._requests:
            count = self._requests[key]
            if count >= self.max_per_minute:
                return JSONResponse(status_code=429, content={"error": "请求过于频繁，请稍后再试"})
            self._requests[key] = count + 1
        else:
            self._requests[key] = 1

        return await call_next(request)
