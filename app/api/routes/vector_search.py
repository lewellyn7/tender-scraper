"""向量语义检索 API"""

from typing import Optional
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.services.vector_store import get_vector_store
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/vector", tags=["向量检索"])


@router.get("/search")
async def vector_search(
    q: str = Query(..., min_length=1, max_length=500, description="自然语言检索查询"),
    top_k: int = Query(5, ge=1, le=50),
    source: Optional[str] = Query(None, description="来源过滤，如 ccgp, ggzy"),
    user_id: str = Query(..., dependencies=[get_current_user]),
):
    """
    向量语义检索接口

    基于文本语义相似度检索招标文档。
    支持 metadata 过滤。
    """
    filters = {}
    if source:
        filters["source"] = source

    store = get_vector_store()
    results = store.search(query=q, top_k=top_k, filters=filters or None)

    return JSONResponse({
        "query": q,
        "total": len(results),
        "results": results,
    })


@router.post("/upsert")
async def vector_upsert(
    docs: list,
    user_id: str = Query(..., dependencies=[get_current_user]),
):
    """
    批量添加/更新向量文档

    Body: List[{"id": str, "text": str, "metadata": dict}]
    """
    if not docs:
        return JSONResponse({"inserted": 0})

    # 简单校验
    for d in docs:
        if not d.get("id") or not d.get("text"):
            return JSONResponse(
                {"error": "Each doc must have non-empty 'id' and 'text'"},
                status_code=400,
            )

    store = get_vector_store()
    result = store.upsert_documents(docs)
    return JSONResponse(result)


@router.delete("")
async def vector_delete(
    ids: str = Query(..., description="逗号分隔的 ID 列表"),
    user_id: str = Query(..., dependencies=[get_current_user]),
):
    """删除指定 ID 的向量"""
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    store = get_vector_store()
    result = store.delete(id_list)
    return JSONResponse(result)


@router.get("/stats")
async def vector_stats():
    """向量库统计信息"""
    store = get_vector_store()
    return JSONResponse(store.stats())
