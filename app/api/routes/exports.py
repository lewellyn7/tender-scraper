"""导出路由"""

import io

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.database import get_db
from app.security.audit import write_audit_log, EVENT_DATA_EXPORT

router = APIRouter(prefix="/api/export", tags=["导出"])


def _get_user_from_request(request: Request):
    """从请求中获取用户ID（未登录抛出 401）"""
    token = request.cookies.get("session_token") or request.headers.get("X-Session-Token")
    if not token:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="未登录")
    from app.utils.session import get_user_from_session
    user = get_user_from_session(token)
    if not user:
        from fastapi import HTTPException
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
def export_csv(request: Request, keyword: str = Query(""), category: str = Query("")):
    """导出 CSV"""
    import csv

    user_id = _get_user_from_request(request)
    db = get_db()
    conn = db._get_conn()

    conditions = ["1=1"]
    params = []
    if keyword:
        conditions.append("(title LIKE ? OR description LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])

    where = " AND ".join(conditions)
    rows = conn.execute(f"SELECT * FROM favorites WHERE {where} LIMIT 10000", params).fetchall()
    row_count = len(rows)

    output = io.StringIO()
    writer = csv.DictWriter(
        output, fieldnames=["title", "tender_type", "budget", "publish_date", "project_url"]
    )
    writer.writeheader()
    for row in rows:
        r = dict(row) if not hasattr(row, 'get') else row
        writer.writerow(
            {
                "title": r.get("title", ""),
                "tender_type": r.get("tender_type", ""),
                "budget": r.get("budget", ""),
                "publish_date": r.get("publish_date", ""),
                "project_url": r.get("project_url", ""),
            }
        )

    output.seek(0)

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
        io.StringIO(output.getvalue()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=projects.csv"},
    )
