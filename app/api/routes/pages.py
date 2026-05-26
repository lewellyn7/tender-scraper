"""页面渲染路由 — 全部需要登录"""

from pathlib import Path
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api.dependencies import get_current_user

router = APIRouter(tags=["页面"])

# templates 目录: 项目根目录 / app / templates
_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _get_user_info(request) -> dict:
    """获取用户信息"""
    try:
        # 自用模式：返回虚拟 admin 用户
        from app.config.settings import get_settings
        if get_settings().is_self_mode:
            return {"user_id": "admin", "username": "admin", "role": "admin", "display_name": "系统管理员"}

        token = request.cookies.get("session_token") or request.headers.get("X-Session-Token")
        if token:
            from app.utils.session import get_user_from_session
            user = get_user_from_session(token)
            if user:
                return user
    except Exception:
        pass
    return {"role": "guest", "username": "", "display_name": ""}


def _require_auth(request: Request) -> dict:
    """页面路由鉴权：未登录则重定向到 /login"""
    user = _get_user_info(request)
    if user.get("role") == "guest":
        return None  # 未登录
    return user


def _render(request: Request, template: str, extra: dict = None):
    """统一渲染"""
    user = _get_user_info(request)
    ctx = {"request": request, "user_info": user}
    if extra:
        ctx.update(extra)
    return _templates.TemplateResponse(request, template, ctx)


# ── 登录页（无需认证）──────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def get_login_page(request: Request):
    """登录页面 — 未登录用户访问"""
    user = _get_user_info(request)
    if user.get("role") != "guest":
        return RedirectResponse(url="/data", status_code=302)
    return _templates.TemplateResponse(request, "login.html", {"request": request, "user_info": user})


# ── 需要认证的页面 ─────────────────────────────────────────────

@router.get("/dashboard")
async def dashboard_page(request: Request):
    """仪表盘页面"""
    user = _get_user_info(request)
    if user.get("role") == "guest":
        return RedirectResponse(url="/login?redirect=/dashboard", status_code=302)
    return _render(request, "dashboard.html")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页 — 已登录则跳转数据页，未登录跳转登录页"""
    user = _get_user_info(request)
    if user.get("role") == "guest":
        return RedirectResponse(url="/login", status_code=302)
    return RedirectResponse(url="/data", status_code=302)


@router.get("/content", response_class=HTMLResponse)
async def get_content(request: Request):
    """采集内容页面 -> 重定向到 /data"""
    return RedirectResponse(url="/data", status_code=302)


@router.get("/data", response_class=HTMLResponse)
async def get_data(request: Request):
    """数据管理页面"""
    user = _get_user_info(request)
    if user.get("role") == "guest":
        return RedirectResponse(url="/login", status_code=302)
    return _render(request, "data.html")


@router.get("/tasks", response_class=HTMLResponse)
async def get_tasks_page(request: Request):
    """任务管理页面"""
    user = _get_user_info(request)
    if user.get("role") == "guest":
        return RedirectResponse(url="/login", status_code=302)
    return _render(request, "tasks.html")


@router.get("/settings", response_class=HTMLResponse)
async def get_settings_page(request: Request):
    """系统设置页面"""
    user = _get_user_info(request)
    if user.get("role") == "guest":
        return RedirectResponse(url="/login", status_code=302)
    return _render(request, "settings.html")


@router.get("/favorites", response_class=HTMLResponse)
async def get_favorites_page(request: Request):
    """收藏页面"""
    user = _get_user_info(request)
    if user.get("role") == "guest":
        return RedirectResponse(url="/login", status_code=302)
    return _render(request, "favorites.html")


@router.get("/analytics", response_class=HTMLResponse)
async def get_analytics_page(request: Request):
    """统计分析页面"""
    user = _get_user_info(request)
    if user.get("role") == "guest":
        return RedirectResponse(url="/login", status_code=302)
    return _render(request, "analytics.html")


@router.get("/logs", response_class=HTMLResponse)
async def get_logs_page(request: Request):
    """日志页面"""
    user = _get_user_info(request)
    if user.get("role") == "guest":
        return RedirectResponse(url="/login", status_code=302)
    return _render(request, "logs.html")


@router.get("/qualifications", response_class=HTMLResponse)
async def get_qualifications_page(request: Request):
    """投标资质管理页面"""
    user = _get_user_info(request)
    if user.get("role") == "guest":
        return RedirectResponse(url="/login", status_code=302)
    return _render(request, "qualifications.html")


@router.get("/documents/upload", response_class=HTMLResponse)
async def get_document_upload_page(request: Request):
    """文档上传已合并到资质管理 — 重定向"""
    return RedirectResponse(url="/qualifications", status_code=302)


@router.get("/nl-query", response_class=HTMLResponse)
async def get_nl_query_page(request: Request):
    """自然语言招标查询页面"""
    user = _get_user_info(request)
    if user.get("role") == "guest":
        return RedirectResponse(url="/login", status_code=302)
    return _render(request, "nl_query.html")
