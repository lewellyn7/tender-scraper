"""任务管理页面路由"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

router = APIRouter()

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

@router.get("/tasks", response_class=HTMLResponse)
async def get_tasks_page(request: Request):
    """任务管理页"""
    from app.api.routes import _get_user_info
    user_info = _get_user_info(request)
    return _templates.TemplateResponse(
        request, 
        "tasks.html", 
        {"request": request, "user_info": user_info}
    )
