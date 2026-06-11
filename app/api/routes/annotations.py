"""标注路由"""

from fastapi import APIRouter, Body, Query, Depends, Request
from fastapi.responses import JSONResponse
from loguru import logger

from app.database import get_db
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/annotations", tags=["标注"])


@router.get("")
def get_annotations(limit: int = Query(500, ge=1, le=1000), user_id: str = Depends(get_current_user)):
    """获取所有标注"""
    db = get_db()
    annotations = db.get_all_annotations(limit=limit)
    return JSONResponse({"annotations": annotations})


@router.get("/{project_url}")
def get_annotation(project_url: str, user_id: str = Depends(get_current_user)):
    """获取单个项目标注"""
    db = get_db()
    annotation = db.get_annotation(project_url)
    if annotation:
        return JSONResponse(annotation)
    return JSONResponse({"error": "标注不存在"}, status_code=404)


@router.post("")
def add_annotation(
    request: Request,
    data: dict = Body(...),
):
    """添加/更新标注

    2026-06-11 修复: 端点签名错配 — 之前期望 4 个独立 Body 字段
    (project_url, note, priority, tags), 但前端 base.html authFetch
    总是发 1 个 dict body, 导致 FastAPI 把整个 dict 当作 project_url
    参数值, db 写入失败.
    修复: 改成 data: dict = Body(...) 模式, 与 annotations_presets.py:33
    完全一致, 前端 POST /api/annotations 的 dict body 可被正确解析.
    """
    user = get_current_user(request)
    project_url = data.get("project_url", "")
    note = data.get("note", "")
    priority = data.get("priority", "normal")
    tags = data.get("tags", [])
    db = get_db()
    try:
        success = db.add_annotation(project_url, note, priority, tags)
        if success:
            return JSONResponse({"success": True})
        return JSONResponse({"success": False, "detail": "数据库写入失败"}, status_code=500)
    except Exception as e:
        logger.error(f"add_annotation error: {e}")
        return JSONResponse({"success": False, "detail": str(e)}, status_code=500)
