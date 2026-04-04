"""预设路由"""

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from app.database import get_db

router = APIRouter(prefix="/api/presets", tags=["预设"])


@router.get("")
def get_presets():
    """获取所有预设"""
    db = get_db()
    presets = db.get_presets()
    return JSONResponse({"presets": presets})


@router.post("")
def save_preset(
    name: str = Body(...),
    preset_key: str = Body(...),
    filter_config: dict = Body(...),
    is_default: bool = Body(False),
):
    """保存预设"""
    db = get_db()
    success = db.save_preset(name, preset_key, filter_config, is_default)
    if success:
        return JSONResponse({"success": True})
    return JSONResponse({"success": False, "error": "保存失败"}, status_code=500)


@router.delete("/{preset_key}")
def delete_preset(preset_key: str):
    """删除预设"""
    db = get_db()
    success = db.delete_preset(preset_key)
    if success:
        return JSONResponse({"success": True})
    return JSONResponse({"success": False}, status_code=500)
