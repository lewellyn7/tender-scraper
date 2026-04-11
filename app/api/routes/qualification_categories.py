"""资质分类和字段配置 API"""
from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from app.database import get_db
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/qualification-config", tags=["资质配置"])


@router.get("/categories", summary="获取资质分类列表")
def list_categories(user_id: str = Depends(get_current_user)):
    """获取资质分类列表（支持自定义增删）"""
    db = get_db()
    try:
        categories = db.get_qualification_categories()
    except Exception:
        # Fallback: return default categories if method doesn't exist
        categories = [
            {"id": 1, "name": "建筑", "count": 0},
            {"id": 2, "name": "IT", "count": 0},
            {"id": 3, "name": "服务", "count": 0},
            {"id": 4, "name": "设备", "count": 0},
            {"id": 5, "name": "其他", "count": 0},
        ]
    return JSONResponse({"categories": categories})


@router.post("/categories", summary="添加资质分类")
def add_category(data: dict = Body(...), user_id: str = Depends(get_current_user)):
    """添加新资质分类"""
    name = data.get("name", "").strip()
    if not name:
        return JSONResponse({"success": False, "error": "分类名称不能为空"}, status_code=400)
    if len(name) > 20:
        return JSONResponse({"success": False, "error": "分类名称过长"}, status_code=400)

    db = get_db()
    try:
        result = db.add_qualification_category(name)
        if result:
            return JSONResponse({"success": True, "id": result})
        return JSONResponse({"success": False, "error": "添加失败"}, status_code=500)
    except Exception as e:
        # If method doesn't exist, return error
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.delete("/categories/{category_id}", summary="删除资质分类")
def delete_category(category_id: int, user_id: str = Depends(get_current_user)):
    """删除资质分类"""
    db = get_db()
    try:
        success = db.delete_qualification_category(category_id)
        if success:
            return JSONResponse({"success": True})
        return JSONResponse({"success": False, "error": "删除失败或分类不存在"}, status_code=404)
    except Exception:
        return JSONResponse({"success": False, "error": "删除失败"}, status_code=500)


@router.get("/fields", summary="获取资质字段配置")
def get_field_config(user_id: str = Depends(get_current_user)):
    """获取资质表单字段配置（哪些字段启用/必填等）"""
    db = get_db()
    try:
        config = db.get_qualification_field_config()
    except Exception:
        # Default field config
        config = {
            "name": {"label": "资质名称", "enabled": True, "required": True, "type": "text"},
            "category": {"label": "类别", "enabled": True, "required": True, "type": "select"},
            "level": {"label": "等级", "enabled": True, "required": False, "type": "select"},
            "certificate_no": {"label": "证书编号", "enabled": True, "required": False, "type": "text"},
            "valid_from": {"label": "有效期起", "enabled": True, "required": False, "type": "date"},
            "valid_to": {"label": "有效期止", "enabled": True, "required": True, "type": "date"},
            "issuer": {"label": "发证机关", "enabled": True, "required": False, "type": "text"},
            "file_path": {"label": "资质文件", "enabled": True, "required": False, "type": "file"},
            "status": {"label": "状态", "enabled": True, "required": True, "type": "select"},
            "notes": {"label": "备注", "enabled": True, "required": False, "type": "textarea"},
        }
    return JSONResponse({"fields": config})


@router.put("/fields", summary="更新资质字段配置")
def update_field_config(data: dict = Body(...), user_id: str = Depends(get_current_user)):
    """更新资质表单字段配置"""
    db = get_db()
    try:
        success = db.update_qualification_field_config(data)
        if success:
            return JSONResponse({"success": True})
        return JSONResponse({"success": False, "error": "更新失败"}, status_code=500)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
