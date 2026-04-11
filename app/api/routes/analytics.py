"""分析统计路由"""

from datetime import datetime, date, timedelta
from fastapi import APIRouter, Query, Depends
from fastapi.responses import JSONResponse

from app.database import get_db
from app.database.db import USE_PG
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/analytics", tags=["分析"])


@router.get("")
def get_analytics(days: int = Query(30, ge=1, le=365), user_id: str = Depends(get_current_user)):
    """获取分析数据"""
    db = get_db()
    conn = db._get_conn()

    start_date = (datetime.now() - timedelta(days=days)).date().isoformat()

    # 获取项目统计
    total_projects = conn.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]
    pending_projects = conn.execute(
        "SELECT COUNT(*) FROM favorites WHERE status = %s", ("pending",)
    ).fetchone()[0]
    matched_projects = conn.execute(
        "SELECT COUNT(*) FROM favorites WHERE title IS NOT NULL AND title != ''"
    ).fetchone()[0]

    # 获取最近趋势（数据库兼容的日期写法）
    if USE_PG:
        date_col = "TO_CHAR(created_at, 'YYYY-MM-DD')"
        trends_sql = f"""
            SELECT {date_col} as date, COUNT(*) as count
            FROM favorites
            WHERE created_at >= %s
            GROUP BY {date_col}
            ORDER BY date
        """
    else:
        date_col = "strftime('%Y-%m-%d', created_at)"
        trends_sql = f"""
            SELECT {date_col} as date, COUNT(*) as count
            FROM favorites
            WHERE date(created_at) >= date('now', '-' || %s || ' days')
            GROUP BY {date_col}
            ORDER BY date
        """
    # PG uses start_date string; SQLite uses days integer in date arithmetic
    trends_param = (start_date,) if USE_PG else (days,)
    trends = conn.execute(trends_sql, trends_param).fetchall()

    # 获取分类统计
    categories = conn.execute("""
        SELECT tender_type, COUNT(*) as count
        FROM favorites
        GROUP BY tender_type
        ORDER BY count DESC
        LIMIT 10
        """).fetchall()

    # 获取预算分布
    budget_dist = conn.execute("""
        SELECT
            CASE
                WHEN budget = '' OR budget IS NULL THEN '未填写'
                WHEN budget LIKE '%万%' AND CAST(replace(replace(budget, '万', ''), '元', '') AS REAL) < 100 THEN '100万以下'
                WHEN budget LIKE '%万%' AND CAST(replace(replace(budget, '万', ''), '元', '') AS REAL) BETWEEN 100 AND 500 THEN '100-500万'
                WHEN budget LIKE '%万%' AND CAST(replace(replace(budget, '万', ''), '元', '') AS REAL) BETWEEN 500 AND 1000 THEN '500-1000万'
                WHEN budget LIKE '%万%' AND CAST(replace(replace(budget, '万', ''), '元', '') AS REAL) > 1000 THEN '1000万以上'
                ELSE '未填写'
            END as range,
            COUNT(*) as count
        FROM favorites
        GROUP BY range
        ORDER BY count DESC
        LIMIT 10
        """).fetchall()

    # 获取来源分布（按域名）
    source_dist = conn.execute("""
        SELECT
            CASE
                WHEN source_url LIKE '%%ccgp%%' THEN '政府采购网'
                WHEN source_url LIKE '%%ggzy%%' THEN '公共资源交易中心'
                WHEN source_url LIKE '%%bidding%%' THEN '招标投标平台'
                WHEN source_url = '' OR source_url IS NULL THEN '未知来源'
                ELSE '其他'
            END as source,
            COUNT(*) as count
        FROM favorites
        GROUP BY source
        ORDER BY count DESC
        LIMIT 10
        """).fetchall()

    # 获取关键词热度（从标题分词统计）
    keyword_heat = {}
    titles = conn.execute(
        "SELECT title FROM favorites LIMIT 100"
    ).fetchall()
    import re
    from collections import Counter
    stop_words = {'的', '了', '和', '与', '或', '及', '的', '在', '为', '于', '对', '等', '由', '以', '被', '将', '把', '给', '向', '从', '通过', '关于', '项目', '采购', '招标', '公告'}
    word_counter = Counter()
    for (title,) in titles:
        if title:
            words = re.findall(r'[\u4e00-\u9fa5]+', title)
            for word in words:
                if len(word) >= 2 and word not in stop_words:
                    word_counter[word] += 1
    keyword_heat = dict(word_counter.most_common(20))

    return JSONResponse(
        {
            "summary": {
                "total": total_projects,
                "pending": pending_projects,
                "matched": matched_projects,
            },
            "trends": [dict(t) for t in trends],
            "categories": [dict(c) for c in categories],
            "budget_dist": [dict(b) for b in budget_dist],
            "source_dist": [dict(s) for s in source_dist],
            "keyword_heat": keyword_heat,
        }
    )
