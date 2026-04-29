"""配置和备份路由"""

from pathlib import Path
from typing import Dict

from fastapi import APIRouter, Body, Query, Depends
from fastapi.responses import FileResponse, JSONResponse

from app.database import get_db
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api", tags=["配置和备份"])
SYS_PATH = Path('/app') if Path('/.dockerenv').exists() else Path(__file__).parent.parent.parent
BACKUP_ROOT = Path(__file__).parent.parent.parent.parent / "data" / "backups"

# ========== config backups ==========


@router.post("/config/backup")
def backup_config(data: Dict = Body(...), user_id: str = Depends(get_current_user)):
    db = get_db()
    db.backup_config(
        version_label=data.get("version_label", ""),
        config_data=data.get("config_data", {}),
        description=data.get("description", ""),
    )
    return {"success": True}


@router.get("/config/backups")
def list_backups(limit: int = Query(10, ge=1, le=50), user_id: str = Depends(get_current_user)):
    backups = get_db().get_config_backups(limit)
    for b in backups:
        b.pop("config_data", None)
    return JSONResponse({"backups": backups})


@router.post("/config/restore/{backup_id}")
def restore_backup(backup_id: str, user_id: str = Depends(get_current_user)):
    b = get_db().restore_config(backup_id)
    if not b:
        return JSONResponse({"error": "backup not found"}, status_code=404)
    return JSONResponse({"backup": b})


# ========== database backups ==========


@router.post("/db/backup")
def backup_database(user_id: str = Depends(get_current_user)):
    backup_path = get_db().backup_database()
    if backup_path:
        return JSONResponse(
            {"success": True, "backup_path": backup_path, "message": "数据库备份成功"}
        )
    return JSONResponse({"success": False, "error": "数据库备份失败"}, status_code=500)


@router.get("/db/backups")
def list_db_backups(limit: int = Query(10, ge=1, le=50), user_id: str = Depends(get_current_user)):
    backups = get_db().list_db_backups(limit)
    return JSONResponse({"backups": backups})


@router.post("/db/restore")
def restore_database(backup_path: str = Body(...), user_id: str = Depends(get_current_user)):
    success = get_db().restore_database(backup_path)
    if success:
        return JSONResponse({"success": True, "message": "数据库恢复成功"})
    return JSONResponse({"success": False, "error": "数据库恢复失败"}, status_code=500)


@router.delete("/db/backup")
def delete_db_backup(backup_path: str = Body(...), user_id: str = Depends(get_current_user)):
    success = get_db().delete_db_backup(backup_path)
    if success:
        return JSONResponse({"success": True, "message": "备份已删除"})
    return JSONResponse({"success": False, "error": "删除失败"}, status_code=500)


@router.get("/db/backup/download")
def download_db_backup(path: str = Query(...), user_id: str = Depends(get_current_user)):
    """下载数据库备份文件 — 仅允许备份目录内的文件"""
    p = Path(path).resolve()
    try:
        p.relative_to(BACKUP_ROOT.resolve())
    except ValueError:
        return JSONResponse({"error": "禁止访问此路径"}, status_code=403)
    if not p.exists():
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    return FileResponse(str(p), filename=p.name, media_type="application/octet-stream")


@router.post("/db/cleanup")
def cleanup_old_backups(keep_count: int = Body(10, ge=1), user_id: str = Depends(get_current_user)):
    deleted = get_db().cleanup_old_backups(keep_count)
    return JSONResponse(
        {"success": True, "deleted": deleted, "message": f"已清理 {deleted} 个旧备份"}
    )
