"""预设路由"""

from datetime import datetime
from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from app.database import get_db
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/presets", tags=["预设"])


def _serialize(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def _serialize_row(row):
    return {k: _serialize(v) for k, v in row.items()}


@router.get("")
def get_presets(user_id: str = Depends(get_current_user)):
    """获取所有预设"""
    db = get_db()
    presets = db.get_presets()
    serialized = [_serialize_row(p) for p in presets]
    return JSONResponse({"presets": serialized})


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
def delete_preset(preset_key: str, user_id: str = Depends(get_current_user)):
    """删除预设"""
    db = get_db()
    success = db.delete_preset(preset_key)
    if success:
        return JSONResponse({"success": True})
    return JSONResponse({"success": False}, status_code=500)
