"""标注和预设路由"""

from typing import Dict

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from app.database import get_db
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api", tags=["标注和预设"])

# ========== annotations ==========


@router.post("/annotations")
def save_annotation(data: Dict = Body(...), user_id: str = Depends(get_current_user)):
    db = get_db()
    db.add_annotation(
        project_url=data.get("project_url", ""),
        note=data.get("note", ""),
        priority=data.get("priority", "normal"),
        tags=data.get("tags", []),
    )
    return {"success": True}


@router.get("/annotations/{project_url}")
def get_annotation(project_url: str, user_id: str = Depends(get_current_user)):
    ann = get_db().get_annotation(project_url)
    return JSONResponse(ann or {})


@router.get("/annotations")
def list_annotations(user_id: str = Depends(get_current_user)):
    return JSONResponse({"annotations": get_db().get_all_annotations()})


# ========== presets ==========


@router.post("/presets")
def save_preset(data: Dict = Body(...), user_id: str = Depends(get_current_user)):
    db = get_db()
    db.save_preset(
        name=data.get("name", ""),
        preset_key=data.get("preset_key", ""),
        filter_config=data.get("filter_config", {}),
        is_default=data.get("is_default", False),
    )
    return {"success": True}


@router.get("/presets")
def list_presets(user_id: str = Depends(get_current_user)):
    return JSONResponse({"presets": get_db().get_presets()})


@router.delete("/presets/{preset_key}")
def delete_preset(preset_key: str, user_id: str = Depends(get_current_user)):
    get_db().delete_preset(preset_key)
    return {"success": True}
