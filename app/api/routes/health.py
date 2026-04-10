"""健康检查路由"""

from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api", tags=["健康检查"])


@router.get("/health")
async def health_check():
    """健康检查端点"""
    return JSONResponse({
        "status": "healthy",
        "version": "3.1",
        "timestamp": datetime.now().isoformat()
    })


@router.get("/health/extended")
async def extended_health():
    """扩展健康检查 - 检查各组件状态"""
    import asyncio
    from app.database.db import get_db
    
    components = {}
    overall_healthy = True
    
    # Database check
    try:
        db = get_db()
        conn = db._get_conn()
        conn.execute("SELECT 1").fetchone()
        components["database"] = {"status": "healthy", "type": "sqlite"}
    except Exception as e:
        components["database"] = {"status": "unhealthy", "error": str(e)}
        overall_healthy = False
    
    # Redis check
    try:
        import os
        redis_url = os.getenv("REDIS_URL", "")
        if redis_url:
            import redis
            r = redis.from_url(redis_url, decode_responses=True)
            r.ping()
            components["redis"] = {"status": "healthy"}
        else:
            components["redis"] = {"status": "not_configured"}
    except Exception as e:
        components["redis"] = {"status": "unhealthy", "error": str(e)}
    
    # Crawler sources check
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Check CQGGZY
            try:
                r = await client.get("https://www.cqggzy.com", follow_redirects=True)
                components["cqggzy"] = {"status": "healthy", "code": r.status_code}
            except:
                components["cqggzy"] = {"status": "unhealthy"}
            
            # Check CCGP
            try:
                r = await client.get("https://www.ccgp-chongqing.gov.cn", follow_redirects=True)
                components["ccgp"] = {"status": "healthy", "code": r.status_code}
            except:
                components["ccgp"] = {"status": "unhealthy"}
    except Exception as e:
        components["crawlers"] = {"status": "unknown", "error": str(e)}
    
    return JSONResponse({
        "status": "healthy" if overall_healthy else "degraded",
        "components": components,
        "timestamp": datetime.now().isoformat()
    })
