"""导出路由"""

import io

from fastapi import APIRouter, Query, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from app.database import get_db
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/export", tags=["导出"])


@router.get("/excel")
def export_excel(
    keyword: str = Query(""),
    category: str = Query(""),
    date_start: str = Query(""),
    date_end: str = Query(""),
    segment_by: str = Query(""),
):
    """导出 Excel"""
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

    output = io.BytesIO()
    try:
        import xlsxwriter

        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet("项目列表")

        headers = ["标题", "类型", "预算", "发布日期", "URL", "状态"]
        for col, header in enumerate(headers):
            worksheet.write(0, col, header)

        for row_idx, row in enumerate(rows, 1):
            worksheet.write(row_idx, 0, row.get("title", ""))
            worksheet.write(row_idx, 1, row.get("tender_type", ""))
            worksheet.write(row_idx, 2, row.get("budget", ""))
            worksheet.write(row_idx, 3, row.get("publish_date", ""))
            worksheet.write(row_idx, 4, row.get("project_url", ""))
            worksheet.write(row_idx, 5, row.get("status", ""))

        workbook.close()
        output.seek(0)

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=projects.xlsx"},
        )
    except ImportError:
        return JSONResponse({"error": "xlsxwriter 未安装"}, status_code=500)


@router.get("/csv")
def export_csv(keyword: str = Query(""), category: str = Query(""), user_id: str = Depends(get_current_user)):
    """导出 CSV"""
    import csv

    db = get_db()
    conn = db._get_conn()

    conditions = ["1=1"]
    params = []
    if keyword:
        conditions.append("(title LIKE ? OR description LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])

    where = " AND ".join(conditions)
    rows = conn.execute(f"SELECT * FROM favorites WHERE {where} LIMIT 10000", params).fetchall()

    output = io.StringIO()
    writer = csv.DictWriter(
        output, fieldnames=["title", "tender_type", "budget", "publish_date", "project_url"]
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "title": row.get("title", ""),
                "tender_type": row.get("tender_type", ""),
                "budget": row.get("budget", ""),
                "publish_date": row.get("publish_date", ""),
                "project_url": row.get("project_url", ""),
            }
        )

    output.seek(0)
    return StreamingResponse(
        io.StringIO(output.getvalue()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=projects.csv"},
    )
