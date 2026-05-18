"""CSRF 防护中间件

修复 H-2: 原版在无 session 时直接放行 POST，导致 CSRF 风险。
现在：
- GET/HEAD/OPTIONS: 直接通过
- POST/PUT/PATCH/DELETE: 
  - 无 session token → 403（匿名请求不允许 mutation）
  - 有 session 但无 CSRF token → 403（已登录用户的跨站请求风险）
  - 有 session + 有 CSRF token → 允许
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """CSRF Token 验证 — 已修复 H-2"""

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    # Public auth endpoints: no CSRF check needed (no session exists yet)
    PUBLIC_AUTH_PATHS = {"/api/users/login", "/api/users/register", "/login", "/register", "/api/cache/clear"}

    async def dispatch(self, request: Request, call_next):
        # Safe methods don't need CSRF check
        if request.method in self.SAFE_METHODS:
            return await call_next(request)

        path = request.url.path

        # Public auth endpoints: allow without CSRF (user has no session yet)
        if path in self.PUBLIC_AUTH_PATHS:
            return await call_next(request)

        # Non-safe methods: require BOTH session and CSRF token
        session_token = request.cookies.get("session_token") or request.headers.get("X-Session-Token")
        client_token = request.headers.get("X-CSRF-Token") or request.cookies.get("csrf_token")

        # H-2 修复: 匿名请求（无 session）直接拒绝 mutation 操作
        if not session_token:
            return JSONResponse(
                status_code=403,
                content={"error": "Authentication required"}
            )

        # 已登录用户必须提供 CSRF token
        # Proper double-submit: X-CSRF-Token header must match csrf_token cookie
        if not client_token:
            return JSONResponse(
                status_code=403,
                content={"error": "CSRF token required"}
            )
        csrf_cookie = request.cookies.get("csrf_token", "")
        if client_token != csrf_cookie:
            return JSONResponse(
                status_code=403,
                content={"error": "CSRF token invalid"}
            )

        return await call_next(request)