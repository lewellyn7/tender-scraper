"""页面渲染路由"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["页面"])


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页/仪表盘"""
    from app.database import get_db

    db = get_db()
    stats = db.get_stats()
    from app.utils.session import get_user_from_session

    user_info = {"role": "guest", "username": "", "display_name": ""}
    try:
        token = request.cookies.get("session_token") or request.headers.get("X-Session-Token")
        if token:
            user = get_user_from_session(token)
            if user:
                user_info = user
    except Exception:
        pass
    std = {
        "total": stats.get("favorites_count", 0),
        "last_run": stats.get("last_run", "-"),
        "matched": 0,
    }
    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html>
    <head><title>仪表盘</title></head>
    <body>
        <h1>招投标采集系统</h1>
        <p>项目数: {std['total']}</p>
        <p>最后运行: {std['last_run']}</p>
        <p>当前用户: {user_info.get('username', 'guest')} ({user_info.get('role', 'guest')})</p>
    </body>
    </html>
    """)


@router.get("/content", response_class=HTMLResponse)
async def get_content(request: Request):
    return HTMLResponse("<html><body><h1>采集内容</h1></body></html>")


@router.get("/data", response_class=HTMLResponse)
async def get_data(request: Request):
    return HTMLResponse("<html><body><h1>数据管理</h1></body></html>")


@router.get("/settings", response_class=HTMLResponse)
async def get_settings_page(request: Request):
    return HTMLResponse("<html><body><h1>设置</h1></body></html>")


@router.get("/favorites", response_class=HTMLResponse)
async def get_favorites_page(request: Request):
    return HTMLResponse("<html><body><h1>收藏</h1></body></html>")


@router.get("/analytics", response_class=HTMLResponse)
async def get_analytics_page(request: Request):
    return HTMLResponse("<html><body><h1>分析</h1></body></html>")


@router.get("/logs", response_class=HTMLResponse)
async def get_logs_page(request: Request):
    return HTMLResponse("<html><body><h1>日志</h1></body></html>")
