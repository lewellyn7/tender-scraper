"""CSRF 防护中间件"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """CSRF Token 验证"""

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

    async def dispatch(self, request: Request, call_next):
        # Safe methods don't need CSRF check
        if request.method in self.SAFE_METHODS:
            return await call_next(request)

        # Non-safe methods require token
        client_token = request.headers.get("X-CSRF-Token") or request.cookies.get("csrf_token")
        if not client_token:
            return JSONResponse(status_code=403, content={"error": "CSRF token required"})

        return await call_next(request)
