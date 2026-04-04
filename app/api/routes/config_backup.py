"""配置和备份路由"""

from pathlib import Path
from typing import Dict

from fastapi import APIRouter, Body, Query
from fastapi.responses import FileResponse, JSONResponse

from app.database import get_db

router = APIRouter(prefix="/api", tags=["配置和备份"])
SYS_PATH = Path(__file__).parent.parent.parent.parent

# ========== config backups ==========


@router.post("/config/backup")
def backup_config(data: Dict = Body(...)):
    db = get_db()
    db.backup_config(
        version_label=data.get("version_label", ""),
        config_data=data.get("config_data", {}),
        description=data.get("description", ""),
    )
    return {"success": True}


@router.get("/config/backups")
def list_backups(limit: int = Query(10, ge=1, le=50)):
    backups = get_db().get_config_backups(limit)
    for b in backups:
        b.pop("config_data", None)
    return JSONResponse({"backups": backups})


@router.post("/config/restore/{backup_id}")
def restore_backup(backup_id: str):
    b = get_db().restore_config(backup_id)
    if not b:
        return JSONResponse({"error": "backup not found"}, status_code=404)
    return JSONResponse({"backup": b})


# ========== database backups ==========


@router.post("/db/backup")
def backup_database():
    backup_path = get_db().backup_database()
    if backup_path:
        return JSONResponse(
            {"success": True, "backup_path": backup_path, "message": "数据库备份成功"}
        )
    return JSONResponse({"success": False, "error": "数据库备份失败"}, status_code=500)


@router.get("/db/backups")
def list_db_backups(limit: int = Query(10, ge=1, le=50)):
    backups = get_db().list_db_backups(limit)
    return JSONResponse({"backups": backups})


@router.post("/db/restore")
def restore_database(backup_path: str = Body(...)):
    success = get_db().restore_database(backup_path)
    if success:
        return JSONResponse({"success": True, "message": "数据库恢复成功"})
    return JSONResponse({"success": False, "error": "数据库恢复失败"}, status_code=500)


@router.delete("/db/backup")
def delete_db_backup(backup_path: str = Body(...)):
    success = get_db().delete_db_backup(backup_path)
    if success:
        return JSONResponse({"success": True, "message": "备份已删除"})
    return JSONResponse({"success": False, "error": "删除失败"}, status_code=500)


@router.get("/db/backup/download")
def download_db_backup(path: str = Query(...)):
    p = Path(path)
    if not p.exists():
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    return FileResponse(path, filename=p.name, media_type="application/octet-stream")


@router.post("/db/cleanup")
def cleanup_old_backups(keep_count: int = Body(10, ge=1)):
    deleted = get_db().cleanup_old_backups(keep_count)
    return JSONResponse(
        {"success": True, "deleted": deleted, "message": f"已清理 {deleted} 个旧备份"}
    )
