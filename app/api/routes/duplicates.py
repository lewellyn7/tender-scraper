"""重复检测路由 — 按项目编号查重"""

from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import get_optional_user
from app.database import get_db
from app.utils.project_linker import normalize_project_no

router = APIRouter(prefix="/api/dedup", tags=["重复检测"])


def _fetch_projects(conn, source, min_len):
    """从指定表查询有 project_no 的记录"""
    if source == "cqggzy":
        table = "projects_cqggzy"
    elif source == "ccgp":
        table = "projects_ccgp"
    else:
        return []

    rows = conn.execute(
        f"""
        SELECT id, title, project_no, url, publish_date,
               LENGTH(full_content) as content_len,
               '{source}' as source
        FROM {table}
        WHERE project_no IS NOT NULL
          AND project_no != ''
          AND LENGTH(project_no) >= %s
        ORDER BY project_no, id
        """,
        (min_len,),
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for k in d:
            if hasattr(d[k], 'isoformat'):
                d[k] = d[k].isoformat()
        result.append(d)
    return result


def _dedup_by_project_no(items):
    """按 project_no 分组，返回重复组"""
    groups = {}
    for r in items:
        proj_no = normalize_project_no(r["project_no"])
        if not proj_no:
            continue
        # Serialize date objects
        for k in r:
            if hasattr(r[k], 'isoformat'):
                r[k] = r[k].isoformat()
        if proj_no not in groups:
            groups[proj_no] = []
        groups[proj_no].append(r)

    duplicate_groups = []
    for proj_no, group in groups.items():
        if len(group) > 1:
            duplicate_groups.append({
                "project_no": group[0]["project_no"],
                "group_key": proj_no,
                "count": len(group),
                "items": group,
            })

    duplicate_groups.sort(key=lambda g: g["count"], reverse=True)
    return duplicate_groups


# ─── GET /dedup ───────────────────────────────────────────────────

@router.get("")
def find_duplicates_by_project_no(
    request: Request,
    source: str = Query("all", description="数据源: cqggzy/ccgp/all"),
    min_len: int = Query(0, ge=0, description="project_no 最小长度过滤"),
):
    """
    按项目编号(project_no)查重。
    
    同一 project_no 的多条记录视为重复项目（如同一项目多次招标）。
    """
    get_optional_user(request)  # optional - public endpoint

    db = get_db()
    conn = db._get_conn()

    if source == "all":
        cqggzy = _fetch_projects(conn, "cqggzy", min_len)
        ccgp = _fetch_projects(conn, "ccgp", min_len)
        items = cqggzy + ccgp
    else:
        items = _fetch_projects(conn, source, min_len)

    groups = _dedup_by_project_no(items)

    flat_groups = [[item for item in g["items"]] for g in groups]

    return JSONResponse({
        "duplicates": flat_groups,
        "count": len(groups),
        "total": sum(g["count"] for g in groups),
        "source": source,
        "groups_meta": [
            {"project_no": g["project_no"], "count": g["count"]}
            for g in groups[:50]
        ],
    })


# ─── GET /dedup/stats ──────────────────────────────────────────────

@router.get("/stats")
def get_duplicate_stats(request: Request):
    """获取查重统计"""
    get_optional_user(request)

    db = get_db()
    conn = db._get_conn()

    stats = {}
    for tbl, label in [("projects_cqggzy", "cqggzy"), ("projects_ccgp", "ccgp")]:
        total = conn.execute(f"""
            SELECT COUNT(*) FROM {tbl}
            WHERE project_no IS NOT NULL AND project_no != ''
        """).fetchone()[0]

        dup = conn.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT project_no FROM {tbl}
                WHERE project_no IS NOT NULL AND project_no != ''
                GROUP BY project_no HAVING COUNT(*) > 1
            ) t
        """).fetchone()[0]

        stats[label] = {"total_with_project_no": total, "duplicate_project_nos": dup}

    return JSONResponse({
        "mode": "project_no",
        "description": "按招标编号/项目编号查重，同一编号的多条记录为重复",
        "sources": stats,
    })