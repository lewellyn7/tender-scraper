"""导出路由"""

import io

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.database import get_db
from app.security.audit import write_audit_log, EVENT_DATA_EXPORT

router = APIRouter(prefix="/api/export", tags=["导出"])


def _get_user_from_request(request: Request):
    """从请求中获取用户ID（未登录抛出 401）"""
    from fastapi import HTTPException
    from app.config.settings import get_settings
    from app.utils.session import get_user_from_session

    # 自用模式：返回 admin 用户
    if get_settings().is_self_mode:
        return "admin"

    token = request.query_params.get("session_token") or request.cookies.get("session_token") or request.headers.get("X-Session-Token")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user = get_user_from_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="无效的session")
    return user.get("user_id")


@router.get("/excel")
def export_excel(
    request: Request,
    keyword: str = Query(""),
    category: str = Query(""),
    date_start: str = Query(""),
    date_end: str = Query(""),
    segment_by: str = Query(""),
):
    """导出 Excel"""
    user_id = _get_user_from_request(request)
    db = get_db()
    conn = db._get_conn()

    conditions = ["1=1"]
    params = []
    if keyword:
        conditions.append("(title LIKE ? OR description LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if category:
        conditions.append("tender_type LIKE ?")
        params.append(f"%{category}%")

    where = " AND ".join(conditions)
    rows = conn.execute(f"SELECT * FROM favorites WHERE {where} LIMIT 10000", params).fetchall()
    row_count = len(rows)

    output = io.BytesIO()
    try:
        import xlsxwriter

        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet("项目列表")

        headers = ["标题", "类型", "预算", "发布日期", "URL", "状态"]
        for col, header in enumerate(headers):
            worksheet.write(0, col, header)

        for row_idx, row in enumerate(rows, 1):
            r = dict(row) if not hasattr(row, 'get') else row
            worksheet.write(row_idx, 0, r.get("title", ""))
            worksheet.write(row_idx, 1, r.get("tender_type", ""))
            worksheet.write(row_idx, 2, r.get("budget", ""))
            worksheet.write(row_idx, 3, r.get("publish_date", ""))
            worksheet.write(row_idx, 4, r.get("project_url", ""))
            worksheet.write(row_idx, 5, r.get("status", ""))

        workbook.close()
        output.seek(0)

        # 审计日志
        write_audit_log(
            EVENT_DATA_EXPORT,
            user_id=user_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            resource="/api/export/excel",
            result="success",
            details={"format": "xlsx", "row_count": row_count, "keyword": keyword},
        )

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=projects.xlsx"},
        )
    except ImportError:
        write_audit_log(
            EVENT_DATA_EXPORT,
            user_id=user_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            resource="/api/export/excel",
            result="failure",
            details={"format": "xlsx", "error": "xlsxwriter not installed"},
        )
        return JSONResponse({"error": "xlsxwriter 未安装"}, status_code=500)


@router.get("/csv")
def export_csv(
    request: Request,
    keyword: str = Query(""),
    category: str = Query(""),
    info_type: str = Query(""),
    date_start: str = Query(""),
    date_end: str = Query(""),
    limit: int = Query(5000),
):
    """导出 CSV（从 projects_cqggzy 表，支持筛选条件）"""
    import csv

    user_id = _get_user_from_request(request)
    db = get_db()
    conn = db._get_conn()

    # 自用模式：不需要 session_token 查询参数
    conditions = ["(NULLIF(project_no, '') IS NOT NULL OR url LIKE 'http%%' OR url LIKE 'https%%')"]
    params = []
    if keyword:
        conditions.append("(title LIKE ? OR content_preview LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if category:
        conditions.append("business_type = ?")
        params.append(category)
    if info_type:
        conditions.append("info_type = ?")
        params.append(info_type)
    if date_start:
        conditions.append("publish_date >= ?")
        params.append(date_start)
    if date_end:
        conditions.append("publish_date <= ?")
        params.append(date_end)

    where = " AND ".join(conditions)
    rows = conn.execute(
        f"SELECT * FROM projects_cqggzy WHERE {where} ORDER BY publish_date DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    row_count = len(rows)

    export_fields = [
        "title", "tender_type", "budget", "publish_date", "source_url",
    ]

    output = io.StringIO()
    # UTF-8 with BOM（Excel 正确识别中文）
    output.write("\ufeff")
    writer = csv.DictWriter(output, fieldnames=export_fields, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        r = dict(row) if not hasattr(row, 'get') else row
        writer.writerow({f: r.get(f, "") for f in export_fields})

    output.seek(0)
    csv_bytes = output.getvalue().encode("utf-8-sig")

    # 审计日志
    write_audit_log(
        EVENT_DATA_EXPORT,
        user_id=user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        resource="/api/export/csv",
        result="success",
        details={"format": "csv", "row_count": row_count, "keyword": keyword},
    )

    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": "attachment; filename=projects.csv"},
    )
