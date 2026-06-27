"""统计路由 - 从 PostgreSQL harvest_records 获取真实统计数据"""

import os
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from app.database import get_db
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/stats", tags=["统计"])

def _get_pg_conn():
    """获取 PostgreSQL 连接"""
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    if not DATABASE_URL.startswith("postgresql://"):
        return None
    import psycopg2
    from psycopg2 import pool
    _pg_pool = getattr(_get_pg_conn, "_pool", None)
    if _pg_pool is None:
        _pg_pool = pool.ThreadedConnectionPool(
            minconn=2, maxconn=20,
            dsn=DATABASE_URL,
            connect_timeout=10
        )
        _get_pg_conn._pool = _pg_pool
    return _pg_pool.getconn()

@router.get("")
def get_stats(user_id: str = Depends(get_current_user)):
    """获取系统统计 - 从 PostgreSQL harvest_records 查询真实数据"""
    try:
        conn = _get_pg_conn()
        if conn is None:
            # 降级到 SQLite
            db = get_db()
            return JSONResponse(db.get_stats())
        
        cursor = conn.cursor()
        
        # 1. 总采集数
        cursor.execute("SELECT COUNT(*) FROM harvest_records")
        total = cursor.fetchone()[0]
        
        # 2. 今日新增 (今天 00:00 到现在)
        cursor.execute("""
            SELECT COUNT(*) FROM harvest_records 
            WHERE DATE(created_at AT TIME ZONE 'Asia/Shanghai') = DATE(NOW() AT TIME ZONE 'Asia/Shanghai')
        """)
        today = cursor.fetchone()[0]
        
        # 3. 成功率 (最近 24 小时)
        cursor.execute("""
            SELECT COUNT(*) FILTER (WHERE status = 'done'), 
                   COUNT(*) FILTER (WHERE status = 'failed'),
                   COUNT(*)
            FROM harvest_records 
            WHERE created_at >= NOW() - INTERVAL '24 hours'
        """)
        row = cursor.fetchone()
        done_count = row[0] or 0
        failed_count = row[1] or 0
        total_24h = row[2] or 0
        success_rate = f"{(done_count / total_24h * 100):.1f}%" if total_24h > 0 else "0%"
        
        # 4. 最近采集时间
        cursor.execute("""
            SELECT MAX(created_at) FROM harvest_records
        """)
        last_run_row = cursor.fetchone()[0]
        last_run = last_run_row.strftime("%m-%d %H:%M") if last_run_row else "—"
        
        cursor.close()
        # P1: psycopg2 pool 语义 — getconn 后必须 putconn, close() 会泄漏连接
        _pg_pool = getattr(_get_pg_conn, "_pool", None)
        if _pg_pool:
            _pg_pool.putconn(conn)
        else:
            conn.close()
        
        return JSONResponse({
            "total": total,
            "today": today,
            "filtered": today,  # 别名
            "success_rate": success_rate,
            "last_run": last_run,
            "running": 1,  # 默认采集器运行中
            "favorites": 0,
            "new_today": today
        })
        
    except Exception as e:
        # 降级到 SQLite
        db = get_db()
        return JSONResponse(db.get_stats())

@router.get("/user")
def get_user_stats(user_id: str = Depends(get_current_user)):
    """获取用户统计"""
    db = get_db()
    return JSONResponse(db.get_user_stats())
