"""标注路由"""

from fastapi import APIRouter, Body, Query, Depends
from fastapi.responses import JSONResponse

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
    project_url: str = Body(...),
    note: str = Body(""),
    priority: str = Body("normal"),
    tags: list = Body([]),
):
    """添加/更新标注"""
    db = get_db()
    success = db.add_annotation(project_url, note, priority, tags)
    if success:
        return JSONResponse({"success": True})
    return JSONResponse({"success": False}, status_code=500)
