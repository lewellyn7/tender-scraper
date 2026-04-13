"""分析统计路由 - 基于收藏项目分析"""

from datetime import datetime, timedelta
from fastapi import APIRouter, Query, Depends
from fastapi.responses import JSONResponse
import re
from collections import Counter

from app.database import get_db
from app.database.db import USE_PG
from app.api.dependencies import get_current_user
from app.services.health_monitor import get_health_monitor

router = APIRouter(prefix="/api/analytics", tags=["分析"])

STOP_WORDS = {
    '的', '了', '和', '与', '或', '及', '在', '为', '于', '对', '等',
    '由', '以', '被', '将', '把', '给', '向', '从', '通过', '关于',
    '项目', '采购', '招标', '公告', '进行中', '公告的', '一', '二', '三'
}


@router.get("")
def get_analytics(
    days: int = Query(30, ge=1, le=365),
    user_id: str = Depends(get_current_user),
):
    """获取收藏项目分析数据"""
    db = get_db()
    conn = db._get_conn()
    
    table = "favorites"
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    # 总数
    total_row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    total = total_row[0] if total_row else 0
    
    # 待处理
    pending_row = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE status = 'pending' OR status = '' OR status IS NULL"
    ).fetchone()
    pending = pending_row[0] if pending_row else 0
    
    # 有预算
    budget_row = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE budget IS NOT NULL AND budget != ''"
    ).fetchone()
    matched = budget_row[0] if budget_row else 0
    
    # 趋势
    if USE_PG:
        trends_sql = f"""
            SELECT DATE(created_at) as date, COUNT(*) as count
            FROM {table}
            WHERE created_at >= %s
            GROUP BY DATE(created_at)
            ORDER BY date
        """
        trends = conn.execute(trends_sql, (start_date,)).fetchall()
    else:
        trends_sql = f"""
            SELECT date(created_at) as date, COUNT(*) as count
            FROM {table}
            WHERE created_at >= ?
            GROUP BY date(created_at)
            ORDER BY date
        """
        trends = conn.execute(trends_sql, (start_date,)).fetchall()
    
    # 分类统计 (tender_type)
    if USE_PG:
        categories_sql = """
            SELECT COALESCE(tender_type, '') as category, COUNT(*) as count
            FROM favorites
            GROUP BY tender_type
            ORDER BY count DESC
            LIMIT 10
        """
    else:
        categories_sql = """
            SELECT COALESCE(tender_type, '') as category, COUNT(*) as count
            FROM favorites
            GROUP BY tender_type
            ORDER BY count DESC
            LIMIT 10
        """
    categories = conn.execute(categories_sql).fetchall()
    
    # 预算分布
    if USE_PG:
        budget_dist_sql = """
            SELECT
                CASE
                    WHEN budget IS NULL OR budget = '' THEN '未填写'
                    WHEN budget ~ '^[0-9.]+' AND CAST(regexp_replace(budget, '[^0-9.]', '', 'g') AS NUMERIC) < 100 THEN '100 万以下'
                    WHEN budget ~ '^[0-9.]+' AND CAST(regexp_replace(budget, '[^0-9.]', '', 'g') AS NUMERIC) BETWEEN 100 AND 500 THEN '100-500 万'
                    WHEN budget ~ '^[0-9.]+' AND CAST(regexp_replace(budget, '[^0-9.]', '', 'g') AS NUMERIC) BETWEEN 500 AND 1000 THEN '500-1000 万'
                    WHEN budget ~ '^[0-9.]+' AND CAST(regexp_replace(budget, '[^0-9.]', '', 'g') AS NUMERIC) > 1000 THEN '1000 万以上'
                    ELSE '未填写'
                END as range,
                COUNT(*) as count
            FROM favorites
            GROUP BY range
            ORDER BY count DESC
        """
    else:
        budget_dist_sql = """
            SELECT
                CASE
                    WHEN budget IS NULL OR budget = '' THEN '未填写'
                    WHEN CAST(replace(replace(budget, '万', ''), '元', '') AS REAL) < 100 THEN '100 万以下'
                    WHEN CAST(replace(replace(budget, '万', ''), '元', '') AS REAL) BETWEEN 100 AND 500 THEN '100-500 万'
                    WHEN CAST(replace(replace(budget, '万', ''), '元', '') AS REAL) BETWEEN 500 AND 1000 THEN '500-1000 万'
                    WHEN CAST(replace(replace(budget, '万', ''), '元', '') AS REAL) > 1000 THEN '1000 万以上'
                    ELSE '未填写'
                END as range,
                COUNT(*) as count
            FROM favorites
            GROUP BY range
            ORDER BY count DESC
        """
    budget_dist = conn.execute(budget_dist_sql).fetchall()
    
    # 来源分布
    if USE_PG:
        source_dist_sql = """
            SELECT
                CASE
                    WHEN source_url LIKE '%ccgp%' THEN '政府采购网'
                    WHEN source_url LIKE '%ggzy%' THEN '公共资源交易中心'
                    WHEN source_url LIKE '%bidding%' THEN '招标投标平台'
                    WHEN source_url IS NULL OR source_url = '' THEN '未知来源'
                    ELSE '其他'
                END as source,
                COUNT(*) as count
            FROM favorites
            GROUP BY source
            ORDER BY count DESC
        """
    else:
        source_dist_sql = """
            SELECT
                CASE
                    WHEN source_url LIKE '%ccgp%' THEN '政府采购网'
                    WHEN source_url LIKE '%ggzy%' THEN '公共资源交易中心'
                    WHEN source_url LIKE '%bidding%' THEN '招标投标平台'
                    WHEN source_url IS NULL OR source_url = '' THEN '未知来源'
                    ELSE '其他'
                END as source,
                COUNT(*) as count
            FROM favorites
            GROUP BY source
            ORDER BY count DESC
        """
    source_dist = conn.execute(source_dist_sql).fetchall()
    
    # 关键词热度
    titles = conn.execute(f"SELECT title FROM {table} LIMIT 200").fetchall()
    word_counter = Counter()
    for (title,) in titles:
        if title:
            words = re.findall(r'[\u4e00-\u9fa5]{2,}', str(title))
            for word in words:
                if word not in STOP_WORDS:
                    word_counter[word] += 1
    keyword_heat = dict(word_counter.most_common(20))
    
    # Convert date objects to strings for JSON serialization
    def serialize_row(row):
        result = {}
        for k, v in row.items():
            if hasattr(v, 'isoformat'):
                result[k] = v.isoformat()
            else:
                result[k] = v
        return result
    
    return JSONResponse({
        "summary": {
            "total": total,
            "pending": pending,
            "matched": matched,
        },
        "trends": [serialize_row(t) for t in trends],
        "categories": [serialize_row(c) for c in categories],
        "budget_dist": [serialize_row(b) for b in budget_dist],
        "source_dist": [serialize_row(s) for s in source_dist],
        "keyword_heat": keyword_heat,
        "days": days,
    })


@router.get("/health")
def get_analytics_health(
    user_id: str = Depends(get_current_user),
):
    """获取采集系统健康度数据（供仪表盘使用）"""
    monitor = get_health_monitor()
    return JSONResponse(monitor.get_current_status())
