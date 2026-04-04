"""分析统计路由"""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.database import get_db

router = APIRouter(prefix="/api/analytics", tags=["分析"])


@router.get("")
def get_analytics(days: int = Query(30, ge=1, le=365)):
    """获取分析数据"""
    db = get_db()
    conn = db._get_conn()

    # 获取项目统计
    total_projects = conn.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]
    pending_projects = conn.execute(
        "SELECT COUNT(*) FROM favorites WHERE status = ?", ("pending",)
    ).fetchone()[0]
    matched_projects = conn.execute(
        "SELECT COUNT(*) FROM favorites WHERE keywords_matched = 1"
    ).fetchone()[0]

    # 获取最近趋势
    trends = conn.execute(
        """
        SELECT DATE(created_at) as date, COUNT(*) as count
        FROM favorites
        WHERE created_at >= DATE('now', ? || ' days')
        GROUP BY DATE(created_at)
        ORDER BY date
        """,
        (-days,),
    ).fetchall()

    # 获取分类统计
    categories = conn.execute("""
        SELECT tender_type, COUNT(*) as count
        FROM favorites
        GROUP BY tender_type
        ORDER BY count DESC
        LIMIT 10
        """).fetchall()

    return JSONResponse(
        {
            "summary": {
                "total": total_projects,
                "pending": pending_projects,
                "matched": matched_projects,
            },
            "trends": [dict(t) for t in trends],
            "categories": [dict(c) for c in categories],
        }
    )
