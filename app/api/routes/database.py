"""数据库路由"""

from pathlib import Path

from fastapi import APIRouter, Body, Query
from fastapi.responses import FileResponse, JSONResponse

from app.database import get_db

router = APIRouter(prefix="/api/db", tags=["数据库"])


@router.post("/backup")
def create_backup():
    """创建数据库备份"""
    backup_path = get_db().backup_database()
    if backup_path:
        return JSONResponse({"success": True, "backup_path": backup_path})
    return JSONResponse({"success": False, "error": "备份失败"}, status_code=500)


@router.get("/backups")
def list_backups(limit: int = Query(10, ge=1, le=50)):
    """列出备份"""
    backups = get_db().list_db_backups(limit)
    return JSONResponse({"backups": backups})


@router.post("/restore")
def restore_backup(backup_path: str = Body(...)):
    """恢复数据库"""
    success = get_db().restore_database(backup_path)
    if success:
        return JSONResponse({"success": True})
    return JSONResponse({"success": False, "error": "恢复失败"}, status_code=500)


@router.delete("/backup")
def delete_backup(backup_path: str = Body(...)):
    """删除备份"""
    success = get_db().delete_db_backup(backup_path)
    if success:
        return JSONResponse({"success": True})
    return JSONResponse({"success": False, "error": "删除失败"}, status_code=500)


@router.post("/cleanup")
def cleanup_old_backups(keep_count: int = Body(10, ge=1)):
    """清理旧备份"""
    deleted = get_db().cleanup_old_backups(keep_count)
    return JSONResponse({"success": True, "deleted": deleted})


@router.get("/backup/download")
def download_backup(path: str = Query(...)):
    """下载备份文件"""
    p = Path(path)
    if not p.exists():
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    return FileResponse(path, filename=p.name, media_type="application/octet-stream")
