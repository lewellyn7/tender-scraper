"""投标主体资质管理 API 路由"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request, Depends
from fastapi.responses import JSONResponse

from app.database import get_db
from app.services.qualification_matcher import QualificationMatcher
from app.api.dependencies import get_current_user
from app.services.qualification_matcher import QualificationMatcher
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/bidder-qualifications", tags=["资质管理"])


def _normalize_status(q: dict) -> dict:
    """规范化资质状态：自动将过期资质的 status 更新为'过期'"""
    if q.get("valid_to"):
        try:
            valid_to = date.fromisoformat(str(q["valid_to"]))
            if valid_to < date.today() and q.get("status") == "有效":
                q["status"] = "过期"
        except (ValueError, TypeError):
            pass
    return q


@router.post("", summary="创建资质")
def create_qualification(request: Request, data: dict = Body(...), user_id: str = Depends(get_current_user)):
    """创建新资质记录"""
    if not data.get("name"):
        raise HTTPException(status_code=400, detail="资质名称不能为空")

    db = get_db()
    qid = db.add_qualification(data)
    if qid is None:
        return JSONResponse({"success": False, "error": "创建失败"}, status_code=500)
    q = db.get_qualification(qid)
    return JSONResponse({"success": True, "id": qid, "qualification": _normalize_status(q)})


@router.get("", summary="资质列表")
def list_qualifications(
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """获取资质列表，支持过滤和分页"""
    db = get_db()
    items, total = db.get_qualifications(
        category=category,
        status=status,
        search=search,
        page=page,
        page_size=page_size,
    )
    items = [_normalize_status(it) for it in items]
    return JSONResponse({
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
    })


@router.get("/expiring", summary="即将过期资质")
def expiring_qualifications(days: int = Query(30, ge=1, le=365), user_id: str = Depends(get_current_user)):
    """获取 N 天内即将过期的资质"""
    db = get_db()
    items = db.get_qualifications_expiring(days=days)
    items = [_normalize_status(it) for it in items]
    return JSONResponse({"items": items, "count": len(items)})


@router.get("/match/{tender_id}", summary="招标项目资质匹配")
def match_qualifications(tender_id: int, user_id: str = Depends(get_current_user)):
    """对指定招标项目进行资质自动匹配"""
    db = get_db()
    tender = db.get_tender_requirements(tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail="招标项目不存在")

    qualifications, _ = db.get_qualifications(page=1, page_size=500)
    qualifications = [_normalize_status(q) for q in qualifications]

    matcher = QualificationMatcher()
    result = matcher.match(tender, qualifications)
    return JSONResponse(result)


@router.get("/{qid}", summary="资质详情")
def get_qualification(qid: int, user_id: str = Depends(get_current_user)):
    """获取单条资质详情"""
    db = get_db()
    q = db.get_qualification(qid)
    if not q:
        raise HTTPException(status_code=404, detail="资质不存在")
    return JSONResponse({"qualification": _normalize_status(q)})


@router.put("/{qid}", summary="更新资质")
def update_qualification(qid: int, data: dict = Body(...), user_id: str = Depends(get_current_user)):
    """更新资质记录"""
    db = get_db()
    existing = db.get_qualification(qid)
    if not existing:
        raise HTTPException(status_code=404, detail="资质不存在")

    success = db.update_qualification(qid, data)
    if not success:
        return JSONResponse({"success": False, "error": "更新失败"}, status_code=500)
    q = db.get_qualification(qid)
    return JSONResponse({"success": True, "qualification": _normalize_status(q)})


@router.delete("/{qid}", summary="删除资质")
def delete_qualification(qid: int, user_id: str = Depends(get_current_user)):
    """删除资质记录"""
    db = get_db()
    existing = db.get_qualification(qid)
    if not existing:
        raise HTTPException(status_code=404, detail="资质不存在")
    db.delete_qualification(qid)
    return JSONResponse({"success": True})


@router.post("/{qid}/link/{tender_id}", summary="关联招标项目")
def link_tender(qid: int, tender_id: int, user_id: str = Depends(get_current_user)):
    """将招标项目关联到资质"""
    db = get_db()
    existing = db.get_qualification(qid)
    if not existing:
        raise HTTPException(status_code=404, detail="资质不存在")
    tender = db.get_tender_requirements(tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail="招标项目不存在")
    success = db.link_tender_to_qualification(qid, tender_id)
    return JSONResponse({"success": success})
