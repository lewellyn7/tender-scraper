"""API 路由 - 页面渲染部分"""

import json
import os
import sys
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from loguru import logger

sys_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, sys_path)

router = APIRouter()
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _get_user_info(request) -> dict:
    """获取用户信息"""
    try:
        token = request.cookies.get("session_token") or request.headers.get("X-Session-Token")
        if token:
            from app.utils.session import get_user_from_session

            user = get_user_from_session(token)
            if user:
                return user
    except Exception as e:
        logger.warning(f"Failed to get user info: {e}")
    return {"role": "guest", "username": "", "display_name": ""}


# ========== 页面渲染 ==========


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页/仪表盘"""
    from app.api.routes.projects import _load_projects
    from app.database import get_db

    db = get_db()
    projects, total = _load_projects()
    std = {
        "total": total,
        "last_run": "-",
        "matched": len([p for p in projects if p.get("keywords_matched")]),
    }

    data_file = Path(sys_path) / "output" / "latest.json"
    if data_file.exists():
        try:
            with open(data_file, encoding="utf-8") as f:
                d = json.load(f)
                std["last_run"] = d.get("last_run", "-")
        except Exception:
            pass

    user_info = _get_user_info(request)
    std["db_stats"] = db.get_stats()
    return _templates.TemplateResponse(
        request, "dashboard.html", {"request": request, "stats": std, "user_info": user_info}
    )


@router.get("/content", response_class=HTMLResponse)
async def get_content(request: Request):
    """数据内容页"""
    user_info = _get_user_info(request)
    return _templates.TemplateResponse(
        request, "data.html", {"request": request, "user_info": user_info}
    )


@router.get("/data", response_class=HTMLResponse)
async def get_data(request: Request):
    """数据页"""
    user_info = _get_user_info(request)
    return _templates.TemplateResponse(
        request, "data.html", {"request": request, "user_info": user_info}
    )


@router.get("/settings", response_class=HTMLResponse)
async def get_settings_page(request: Request):
    """设置页"""
    user_info = _get_user_info(request)
    return _templates.TemplateResponse(
        request, "settings.html", {"request": request, "user_info": user_info}
    )


@router.get("/favorites", response_class=HTMLResponse)
async def get_favorites(request: Request):
    """收藏页"""
    user_info = _get_user_info(request)
    return _templates.TemplateResponse(
        request, "favorites.html", {"request": request, "user_info": user_info}
    )


@router.get("/analytics", response_class=HTMLResponse)
async def get_analytics_page(request: Request):
    """分析页"""
    user_info = _get_user_info(request)
    return _templates.TemplateResponse(
        request, "analytics.html", {"request": request, "user_info": user_info}
    )


@router.get("/logs", response_class=HTMLResponse)
async def get_logs_page(request: Request):
    """日志页"""
    user_info = _get_user_info(request)
    return _templates.TemplateResponse(
        request, "logs.html", {"request": request, "user_info": user_info}
    )
