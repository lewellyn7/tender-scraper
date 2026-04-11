"""页面渲染路由"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["页面"])

# templates 目录: 项目根目录 / app / templates
_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _get_user_info(request) -> dict:
    """获取用户信息"""
    try:
        token = request.cookies.get("session_token") or request.headers.get("X-Session-Token")
        if token:
            from app.utils.session import get_user_from_session
            user = get_user_from_session(token)
            if user:
                return user
    except Exception:
        pass
    return {"role": "guest", "username": "", "display_name": ""}


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页/仪表盘"""
    return _templates.TemplateResponse(
        request, "dashboard.html",
        {"request": request, "stats": {}, "user_info": _get_user_info(request)}
    )


@router.get("/content", response_class=HTMLResponse)
async def get_content(request: Request):
    return _templates.TemplateResponse(
        request, "data.html",
        {"request": request, "user_info": _get_user_info(request)}
    )


@router.get("/data", response_class=HTMLResponse)
async def get_data(request: Request):
    """数据管理页面"""
    return _templates.TemplateResponse(
        request, "data.html",
        {"request": request, "user_info": _get_user_info(request)}
    )


@router.get("/settings", response_class=HTMLResponse)
async def get_settings_page(request: Request):
    """系统设置页面"""
    return _templates.TemplateResponse(
        request, "settings.html",
        {"request": request, "user_info": _get_user_info(request)}
    )


@router.get("/favorites", response_class=HTMLResponse)
async def get_favorites_page(request: Request):
    return _templates.TemplateResponse(
        request, "favorites.html",
        {"request": request, "user_info": _get_user_info(request)}
    )


@router.get("/analytics", response_class=HTMLResponse)
async def get_analytics_page(request: Request):
    return _templates.TemplateResponse(
        request, "analytics.html",
        {"request": request, "user_info": _get_user_info(request)}
    )


@router.get("/logs", response_class=HTMLResponse)
async def get_logs_page(request: Request):
    return _templates.TemplateResponse(
        request, "logs.html",
        {"request": request, "user_info": _get_user_info(request)}
    )


@router.get("/qualifications", response_class=HTMLResponse)
async def get_qualifications_page(request: Request):
    """投标资质管理页面"""
    return _templates.TemplateResponse(
        request, "qualifications.html",
        {"request": request, "user_info": _get_user_info(request)}
    )


@router.get("/documents/upload", response_class=HTMLResponse)
async def get_document_upload_page(request: Request):
    """资质文档上传分析页面"""
    return _templates.TemplateResponse(
        request, "document_upload.html",
        {"request": request, "user_info": _get_user_info(request)}
    )


@router.get("/nl-query", response_class=HTMLResponse)
async def get_nl_query_page(request: Request):
    """自然语言招标查询页面"""
    return _templates.TemplateResponse(
        request, "nl_query.html",
        {"request": request, "user_info": _get_user_info(request)}
    )


@router.get("/login", response_class=HTMLResponse)
async def get_login_page(request: Request):
    """登录/注册页面"""
    return _templates.TemplateResponse(
        request, "login.html",
        {"request": request, "user_info": _get_user_info(request)}
    )
