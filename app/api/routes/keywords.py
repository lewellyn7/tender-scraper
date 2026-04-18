"""关键词管理 API"""

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field
from typing import List, Optional
from app.services.keywords_service import KeywordsService
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/keywords", tags=["关键词管理"])


class KeywordAdd(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=100)
    category: str = Field("include", pattern="^(include|exclude)$")
    match_mode: str = Field("exact", pattern="^(exact|fuzzy|partial)$")
    threshold: float = Field(0.8, ge=0.5, le=1.0)


class KeywordUpdate(BaseModel):
    keyword: Optional[str] = Field(None, min_length=1, max_length=100)
    category: Optional[str] = Field(None, pattern="^(include|exclude)$")
    match_mode: Optional[str] = Field(None, pattern="^(exact|fuzzy|partial)$")
    threshold: Optional[float] = Field(None, ge=0.5, le=1.0)
    enabled: Optional[bool] = None


class KeywordMatchRequest(BaseModel):
    texts: List[str] = Field(..., min_items=1, max_items=100)
    categories: Optional[List[str]] = Field(None)


@router.get("")
def list_keywords(user_id: str = Depends(get_current_user)):
    """获取所有关键词"""
    svc = KeywordsService()
    return svc.list_all()


@router.get("/stats")
def get_stats(user_id: str = Depends(get_current_user)):
    """获取关键词统计"""
    svc = KeywordsService()
    return svc.get_stats()


@router.post("")
def add_keyword(
    body: KeywordAdd,
    user_id: str = Depends(get_current_user)
):
    """添加关键词"""
    svc = KeywordsService()
    return svc.add(
        keyword=body.keyword,
        category=body.category,
        match_mode=body.match_mode,
        threshold=body.threshold
    )


@router.patch("/{keyword_id}")
def update_keyword(
    keyword_id: int,
    body: KeywordUpdate,
    user_id: str = Depends(get_current_user)
):
    """更新关键词"""
    svc = KeywordsService()
    data = body.model_dump(exclude_none=True)
    if 'enabled' in data:
        data['enabled'] = 1 if data['enabled'] else 0
    return svc.update(keyword_id, **data)


@router.delete("/{keyword_id}")
def delete_keyword(
    keyword_id: int,
    user_id: str = Depends(get_current_user)
):
    """删除关键词"""
    svc = KeywordsService()
    return svc.delete(keyword_id)


@router.post("/{keyword_id}/toggle")
def toggle_keyword(
    keyword_id: int,
    user_id: str = Depends(get_current_user)
):
    """切换启用状态"""
    svc = KeywordsService()
    return svc.toggle(keyword_id)


@router.post("/match")
def match_keywords(
    body: KeywordMatchRequest,
    user_id: str = Depends(get_current_user)
):
    """
    批量匹配标题
    输入: texts: ["标题1", "标题2"]
    输出: 每个标题的匹配结果
    """
    svc = KeywordsService()
    categories = body.categories or ["include"]
    
    results = []
    for text in body.texts:
        match_result = svc.match(text, categories=categories)
        results.append({
            "text": text,
            "matched": match_result["matched"],
            "scores": match_result["scores"],
            "match_count": len(match_result["matched"])
        })
    
    return {"results": results}


@router.post("/filter")
def filter_titles(
    texts: List[str] = Body(..., min_items=1, max_items=100),
    category: str = Body("include"),
    user_id: str = Depends(get_current_user)
):
    """
    过滤标题 - 只返回匹配的
    """
    svc = KeywordsService()
    results = svc.filter_titles(texts, category=category)
    return {"matched": results, "total": len(results)}


@router.post("/seed")
def seed_keywords(
    user_id: str = Depends(get_current_user)
):
    """填充默认关键词"""
    svc = KeywordsService()
    svc.seed_defaults()
    return {"success": True, "message": "默认关键词已填充"}
