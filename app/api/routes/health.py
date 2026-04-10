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
    from app.database.db import get_db
    import os
    import httpx
    
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
    
    # Crawler sources check - random browser UA to avoid anti-bot detection
    try:
        browser_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        try:
            from app.core.harvest.human_behavior_engine import get_random_user_agent
            browser_ua = get_random_user_agent()
        except ImportError:
            pass
        headers = {
            "User-Agent": browser_ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        async with httpx.AsyncClient(timeout=10.0, headers=headers, follow_redirects=True) as client:
            try:
                r = await client.get("https://www.cqggzy.com")
                components["cqggzy"] = {"status": "healthy", "code": r.status_code}
            except Exception:
                components["cqggzy"] = {"status": "unhealthy"}
            
            try:
                r = await client.get("https://www.ccgp-chongqing.gov.cn")
                components["ccgp"] = {"status": "healthy", "code": r.status_code}
            except Exception:
                components["ccgp"] = {"status": "unhealthy"}
    except Exception as e:
        components["crawlers"] = {"status": "unknown", "error": str(e)}
    
    return JSONResponse({
        "status": "healthy" if overall_healthy else "degraded",
        "components": components,
        "timestamp": datetime.now().isoformat()
    })
