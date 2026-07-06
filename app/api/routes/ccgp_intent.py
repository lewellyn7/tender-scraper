"""CCGP 采购意向 / 需求调查 独立筛选页路由 (2026-07-06 新增)

来源: feat/ccgp-intent-page-2026-07-06
表:   projects_ccgp_intention_demand (migration 004, PR feat/ccgp-intention-demand-2026-07-01)
采集: app.core.harvest.pipeline.run_ccgp_intent_demand_collection
模板: app/templates/ccgp_intent.html (仿 fahcqmu 风格)

端点:
- GET /api/ccgp_intent/projects       列表（keyword / info_type / date range / 分页）
- GET /api/ccgp_intent/project/{url}  详情
- GET /api/ccgp_intent/stats          统计（总数 / 按 info_type / 按日期）
- GET /api/ccgp_intent/health         健康检查（库内行数 + 最新 publish_date）

设计原则:
- 复用 fahcqmu.py 的 helper (1:1 mirror, 仅表名不同)
- 0 模板渲染、0 数据迁移 — 仅查询已落库的 projects_ccgp_intention_demand 表
- 自用模式: get_current_user_id_optional 直接返 'admin'
- 关键词搜索: title + content_preview LIKE
- info_type 限定为 ['采购意向','需求调查'] (防止采集器扩类后越界)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from loguru import logger

from app.database import get_db

router = APIRouter(prefix="/api/ccgp_intent", tags=["CCGP采购意向"])

# 允许的 info_type（防注入 + 未来扩类时显式约束）
ALLOWED_INFO_TYPES = ("采购意向", "需求调查")


# ── 工具函数 ──────────────────────────────────────────────────────
def _get_current_user_id_optional(request: Request) -> Optional[str]:
    """获取当前用户ID（可选）。自用模式免登录返回 'admin'."""
    from app.config.settings import get_settings
    if get_settings().is_self_mode:
        return "admin"
    token = request.cookies.get("session_token") or request.headers.get("X-Session-Token")
    if not token:
        return None
    try:
        from app.utils.session import get_user_from_session
        user = get_user_from_session(token)
        return user["user_id"] if user else None
    except Exception:
        return None


def _row_to_dict(row) -> dict:
    """psycopg2 _DictRow → dict (JSON 兼容处理 datetime / date)."""
    out = {}
    for k, v in dict(row).items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif hasattr(v, "isoformat"):  # date
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _build_where_clause(
    keyword: str = "",
    info_type: str = "",
    date_start: str = "",
    date_end: str = "",
) -> tuple[str, list]:
    """构建 WHERE 子句 + 参数列表."""
    conditions = []
    params = []

    if keyword:
        conditions.append("(title LIKE ? OR content_preview LIKE ?)")
        kw = f"%{keyword}%"
        params.extend([kw, kw])

    if info_type:
        # 白名单校验 — 即使前端传奇怪值也不会拼到 SQL
        if info_type not in ALLOWED_INFO_TYPES:
            info_type = ""
        else:
            conditions.append("info_type = ?")
            params.append(info_type)

    if date_start:
        conditions.append("publish_date >= ?")
        params.append(date_start)

    if date_end:
        conditions.append("publish_date <= ?")
        params.append(date_end)

    where = " AND ".join(conditions) if conditions else "1=1"
    return where, params


# ── 端点 ──────────────────────────────────────────────────────────
@router.get("/projects")
def list_projects(
    request: Request,
    keyword: str = Query("", description="关键词（模糊匹配 title + content_preview）"),
    info_type: str = Query("", description="类型: 采购意向 / 需求调查"),
    date_start: str = Query("", description="起始日期 YYYY-MM-DD"),
    date_end: str = Query("", description="结束日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1, description="页码（1-based）"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数"),
    order_by: str = Query("publish_date_desc", description="排序: publish_date_desc / publish_date_asc / scraped_at_desc"),
):
    """列出 CCGP 采购意向 / 需求调查 项目."""
    db = get_db()
    where, params = _build_where_clause(keyword, info_type, date_start, date_end)

    # 排序
    order_sql = {
        "publish_date_desc": "publish_date DESC NULLS LAST, id DESC",
        "publish_date_asc": "publish_date ASC NULLS LAST, id ASC",
        "scraped_at_desc": "scraped_at DESC NULLS LAST, id DESC",
    }.get(order_by, "publish_date DESC NULLS LAST, id DESC")

    # 总数
    count_sql = f"SELECT COUNT(*) as cnt FROM projects_ccgp_intention_demand WHERE {where}"
    total = db._get_conn().execute(count_sql, params).fetchone()["cnt"]

    # 分页
    offset = (page - 1) * page_size
    list_sql = f"""
        SELECT id, url, title, category, info_type, business_type,
               publish_date, content_preview, full_content, budget, bid_amount,
               region, industry, tender_type, project_overview, bidder_requirements,
               submission_deadline, submission_location,
               contact_name, contact_phone, contact_email,
               scraped_at, scraped_by
        FROM projects_ccgp_intention_demand
        WHERE {where}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
    """
    rows = db._get_conn().execute(list_sql, params + [page_size, offset]).fetchall()

    return JSONResponse({
        "items": [_row_to_dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": (offset + len(rows)) < total,
    })


@router.get("/project/{project_url:path}")
def get_project(request: Request, project_url: str):
    """单条详情（按 URL 精确查询）."""
    db = get_db()
    row = db._get_conn().execute(
        "SELECT * FROM projects_ccgp_intention_demand WHERE url = ?",
        [project_url]
    ).fetchone()
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(_row_to_dict(row))


@router.get("/stats")
def get_stats(
    request: Request,
    info_type: str = Query("", description="按类型筛选: 采购意向 / 需求调查"),
    date_start: str = Query("", description="起始日期 YYYY-MM-DD"),
    date_end: str = Query("", description="结束日期 YYYY-MM-DD"),
):
    """统计: 总数 + 按 info_type + 按发布日期.

    返回结构:
    {
        "total": 1195,
        "by_info_type": {"采购意向": 1000, "需求调查": 195},
        "by_date": [{"date": "2026-07-02", "count": 6}, ...],
        "date_range": {"start": "2026-06-02", "end": "2026-07-02"},
    }
    """
    db = get_db()
    where, params = _build_where_clause("", info_type, date_start, date_end)
    base_where = where

    # 总数
    total = db._get_conn().execute(
        f"SELECT COUNT(*) as cnt FROM projects_ccgp_intention_demand WHERE {base_where}", params
    ).fetchone()["cnt"]

    # 按 info_type
    by_info = db._get_conn().execute(
        f"SELECT info_type, COUNT(*) as cnt FROM projects_ccgp_intention_demand "
        f"WHERE {base_where} GROUP BY info_type ORDER BY cnt DESC",
        params
    ).fetchall()
    by_info_type = {r["info_type"] or "未分类": r["cnt"] for r in by_info}

    # 按发布日期 (近 30 天)
    by_date_rows = db._get_conn().execute(
        f"SELECT publish_date, COUNT(*) as cnt FROM projects_ccgp_intention_demand "
        f"WHERE {base_where} AND publish_date IS NOT NULL "
        f"GROUP BY publish_date ORDER BY publish_date DESC LIMIT 30",
        params
    ).fetchall()
    by_date = [
        {"date": r["publish_date"].isoformat(), "count": r["cnt"]}
        for r in by_date_rows
    ]

    # 数据范围
    range_row = db._get_conn().execute(
        f"SELECT MIN(publish_date) as start, MAX(publish_date) as end "
        f"FROM projects_ccgp_intention_demand WHERE {base_where}",
        params
    ).fetchone()
    date_range = {
        "start": range_row["start"].isoformat() if range_row["start"] else None,
        "end": range_row["end"].isoformat() if range_row["end"] else None,
    }

    return JSONResponse({
        "total": total,
        "by_info_type": by_info_type,
        "by_date": by_date,
        "date_range": date_range,
    })


@router.get("/health")
def health():
    """健康检查: 表行数 + 最新 publish_date."""
    db = get_db()
    try:
        row = db._get_conn().execute(
            "SELECT COUNT(*) as cnt, MAX(publish_date) as last "
            "FROM projects_ccgp_intention_demand"
        ).fetchone()
        by_info = db._get_conn().execute(
            "SELECT info_type, COUNT(*) as cnt FROM projects_ccgp_intention_demand "
            "GROUP BY info_type ORDER BY cnt DESC"
        ).fetchall()
        return JSONResponse({
            "status": "ok",
            "table": "projects_ccgp_intention_demand",
            "total_rows": row["cnt"],
            "last_publish_date": row["last"].isoformat() if row["last"] else None,
            "by_info_type": {r["info_type"]: r["cnt"] for r in by_info},
            "checked_at": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.error(f"[ccgp_intent health] {e}")
        return JSONResponse({
            "status": "error",
            "error": str(e),
        }, status_code=500)