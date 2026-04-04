"""健康检查路由"""

from datetime import datetime

from fastapi import APIRouter, JSONResponse

router = APIRouter(tags=["健康检查"])


@router.get("/health")
async def health_check():
    """健康检查端点"""
    return JSONResponse(
        {"status": "healthy", "version": "3.1", "timestamp": datetime.now().isoformat()}
    )
