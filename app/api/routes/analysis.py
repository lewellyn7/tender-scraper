"""
analysis.py — 中标排名分析 API

端点:
- GET /api/analysis/bid-rank       排名聚合 (政府采购 / 工程招投标)
- GET /api/analysis/bid-detail     单个中标单位明细 (下钻)
- GET /api/analysis/bid-summary    排名概要 (含 Top N + 总数)
"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from loguru import logger

from app.database.db import get_db

router = APIRouter(prefix="/api/analysis", tags=["中标排名分析"])


# ─── 工具函数 ────────────────────────────────────────────────────────────────

def _quarter_range(year: int, quarter: int) -> tuple[date, date]:
    """自然季度 → (start_date, end_date)."""
    q = quarter
    if q == 1:
        return date(year, 1, 1), date(year, 3, 31)
    elif q == 2:
        return date(year, 4, 1), date(year, 6, 30)
    elif q == 3:
        return date(year, 7, 1), date(year, 9, 30)
    elif q == 4:
        return date(year, 10, 1), date(year, 12, 31)
    else:
        raise ValueError(f"quarter must be 1-4, got {quarter}")


def _resolve_period(
    period: str,
    year: Optional[int],
    quarter: Optional[int],
    date_start: Optional[date],
    date_end: Optional[date],
) -> tuple[date, date, dict]:
    """根据 period 参数解析日期范围 + 描述."""
    if period == "quarter":
        if not year or not quarter:
            raise ValueError("period=quarter 时 year 和 quarter 必填")
        d_start, d_end = _quarter_range(year, quarter)
        desc = f"{year} Q{quarter}"
    elif period == "year":
        if not year:
            raise ValueError("period=year 时 year 必填")
        d_start, d_end = date(year, 1, 1), date(year, 12, 31)
        desc = f"{year} 年"
    elif period == "custom":
        if not date_start or not date_end:
            raise ValueError("period=custom 时 date_start 和 date_end 必填")
        d_start, d_end = date_start, date_end
        desc = f"{date_start} ~ {date_end}"
    else:
        raise ValueError(f"period must be quarter|year|custom, got {period}")

    return d_start, d_end, {"label": desc, "year": year, "quarter": quarter}


def _category_filter(category: str, info_type: Optional[str] = None) -> str:
    """category 参数 → SQL info_type 过滤.

    政府采购 → info_type='采购结果公告' (info_type 参数对其忽略, 政府采购只有 1 种)
    工程招投标 → info_type IN ('中标候选人公示', '中标结果公示')
                  + info_type 可进一步过滤:
                  - '中标结果公示' 只看最终中标人 (含金额)
                  - '中标候选人公示' 只看第一候选人 (常无金额)
                  - None / 'all' 不过滤
    """
    if category == "政府采购":
        # 政府采购 只有 '采购结果公告' 1 种, info_type 参数对其忽略
        return "info_type = '采购结果公告'"
    elif category == "工程招投标":
        if info_type and info_type != "all":
            if info_type not in ('中标候选人公示', '中标结果公示'):
                raise ValueError(f"info_type must be 中标结果公示|中标候选人公示|all, got {info_type}")
            return f"info_type = '{info_type}'"
        return "info_type IN ('中标候选人公示', '中标结果公示')"
    else:
        raise ValueError(f"category must be 政府采购|工程招投标, got {category}")


# ─── 端点 1: 排名聚合 ────────────────────────────────────────────────────────

@router.get("/bid-rank")
async def bid_rank(
    category: str = Query(..., description="政府采购 / 工程招投标"),
    period: str = Query("quarter", description="quarter / year / custom"),
    year: Optional[int] = Query(None, description="年份 (period=quarter|year 必填)"),
    quarter: Optional[int] = Query(None, description="1-4 (period=quarter 必填)"),
    date_start: Optional[date] = Query(None, description="period=custom 必填"),
    date_end: Optional[date] = Query(None, description="period=custom 必填"),
    info_type: Optional[str] = Query(None, description="进一步过滤: 中标结果公示 (只看中标人) / 中标候选人公示 / all"),
    sort_by: str = Query("amount", description="amount / count"),
    limit: int = Query(50, ge=1, le=500, description="默认 50, 最大 500"),
):
    """按中标单位聚合: 项目数 + 金额合计 + 均值 + 首次/末次中标日期."""
    try:
        d_start, d_end, desc = _resolve_period(period, year, quarter, date_start, date_end)
        info_filter = _category_filter(category, info_type)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    order_col = "total_amount" if sort_by == "amount" else "project_count"
    sql = f"""
        SELECT
          winner_name,
          COUNT(DISTINCT project_id) AS project_count,
          SUM(bid_amount_num) AS total_amount,
          ROUND(AVG(bid_amount_num), 2) AS avg_amount,
          ROUND(AVG(winner_score), 2) AS avg_score,
          MIN(publish_date) AS first_win,
          MAX(publish_date) AS last_win,
          ARRAY_AGG(DISTINCT info_type) AS info_types,
          COUNT(*) AS bid_rows
        FROM bid_results
        WHERE {info_filter}
          AND publish_date BETWEEN %s AND %s
        GROUP BY winner_name
        ORDER BY {order_col} DESC
        LIMIT %s
    """

    db = get_db()
    cur = db._get_conn().cursor()
    cur.execute(sql, (d_start, d_end, limit))
    rows = cur.fetchall()
    cur.close()

    rankings = []
    for i, (name, count, total, avg, avg_score, first, last, info_types, bid_rows) in enumerate(rows, 1):
        rankings.append({
            "rank": i,
            "winner_name": name,
            "project_count": count,
            "bid_rows": bid_rows,
            "total_amount": float(total) if total else 0,
            "avg_amount": float(avg) if avg else 0,
            "avg_score": float(avg_score) if avg_score else None,
            "first_win": first.isoformat() if first else None,
            "last_win": last.isoformat() if last else None,
            "info_types": list(info_types) if info_types else [],
        })

    # 总览
    total_amount = sum(r["total_amount"] for r in rankings)
    total_projects = sum(r["project_count"] for r in rankings)

    return {
        "period": desc,
        "category": category,
        "date_start": d_start.isoformat(),
        "date_end": d_end.isoformat(),
        "sort_by": sort_by,
        "limit": limit,
        "total_winners": len(rankings),
        "total_amount": round(total_amount, 2),
        "total_projects": total_projects,
        "rankings": rankings,
    }


# ─── 端点 2: 下钻明细 ────────────────────────────────────────────────────────

@router.get("/bid-detail")
async def bid_detail(
    winner_name: str = Query(..., description="中标单位名"),
    category: Optional[str] = Query(None, description="政府采购 / 工程招投标 (可选过滤)"),
    date_start: Optional[date] = Query(None),
    date_end: Optional[date] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
):
    """单个中标单位的中标项目明细 (下钻)."""
    if not date_start:
        date_start = date(2026, 1, 1)
    if not date_end:
        date_end = date.today()

    cat_filter = ""
    params = [winner_name, date_start, date_end]
    if category:
        try:
            cat_filter = f"AND {_category_filter(category)}"
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    sql = f"""
        SELECT
          br.project_id, br.url, br.info_type, br.category, br.package_no,
          br.winner_name, br.winner_rank, br.bid_amount, br.bid_amount_num,
          br.winner_score, br.publish_date,
          p.title, p.publish_date AS p_date
        FROM bid_results br
        LEFT JOIN projects_cqggzy p ON p.id = br.project_id
        WHERE br.winner_name = %s
          AND br.publish_date BETWEEN %s AND %s
          {cat_filter}
        ORDER BY br.publish_date DESC
        LIMIT %s
    """

    db = get_db()
    cur = db._get_conn().cursor()
    cur.execute(sql, (*params, limit))
    rows = cur.fetchall()
    cur.close()

    items = []
    for (proj_id, url, info_type, cat, pkg_no, name, rank, amt_text,
         amt_num, score, pub_date, title, p_date) in rows:
        items.append({
            "project_id": proj_id,
            "title": title or "",
            "url": url,
            "info_type": info_type,
            "category": cat,
            "package_no": pkg_no,
            "winner_rank": rank,
            "bid_amount_text": amt_text,
            "bid_amount": float(amt_num) if amt_num else None,
            "winner_score": float(score) if score else None,
            "publish_date": pub_date.isoformat() if pub_date else None,
        })

    total_amount = sum(i["bid_amount"] or 0 for i in items)
    return {
        "winner_name": winner_name,
        "category": category,
        "date_start": date_start.isoformat(),
        "date_end": date_end.isoformat(),
        "total_projects": len(set(i["project_id"] for i in items)),
        "total_amount": round(total_amount, 2),
        "items": items,
    }


# ─── 端点 3: 综合概要 ────────────────────────────────────────────────────────

@router.get("/bid-summary")
async def bid_summary(
    year: int = Query(..., description="年份, e.g. 2026"),
):
    """年度概要: 各季度 Top 3 + 全年 Top 10."""
    result = {"year": year, "quarters": [], "yearly_top10": None}

    for q in range(1, 5):
        d_start, d_end = _quarter_range(year, q)
        sql = """
            SELECT winner_name,
                   COUNT(DISTINCT project_id) AS pc,
                   SUM(bid_amount_num) AS total
            FROM bid_results
            WHERE publish_date BETWEEN %s AND %s
            GROUP BY winner_name
            ORDER BY total DESC NULLS LAST
            LIMIT 3
        """
        db = get_db()
        cur = db._get_conn().cursor()
        cur.execute(sql, (d_start, d_end))
        rows = cur.fetchall()
        cur.close()

        result["quarters"].append({
            "quarter": q,
            "date_range": f"{d_start} ~ {d_end}",
            "top3": [
                {
                    "rank": i + 1,
                    "winner_name": n,
                    "project_count": pc,
                    "total_amount": float(t or 0),
                }
                for i, (n, pc, t) in enumerate(rows)
            ],
        })

    # 全年 Top 10 (所有 category 混合)
    d_start, d_end = date(year, 1, 1), date(year, 12, 31)
    sql = """
        SELECT winner_name,
               COUNT(DISTINCT project_id) AS pc,
               SUM(bid_amount_num) AS total,
               ARRAY_AGG(DISTINCT info_type) AS types
        FROM bid_results
        WHERE publish_date BETWEEN %s AND %s
        GROUP BY winner_name
        ORDER BY total DESC NULLS LAST
        LIMIT 10
    """
    db = get_db()
    cur = db._get_conn().cursor()
    cur.execute(sql, (d_start, d_end))
    rows = cur.fetchall()
    cur.close()

    result["yearly_top10"] = [
        {
            "rank": i + 1,
            "winner_name": n,
            "project_count": pc,
            "total_amount": float(t or 0),
            "info_types": list(types) if types else [],
        }
        for i, (n, pc, t, types) in enumerate(rows)
    ]

    return result