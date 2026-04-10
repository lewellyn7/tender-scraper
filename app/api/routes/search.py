"""语义搜索路由"""

from typing import List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from loguru import logger

from services.ragflow_service import get_ragflow_service

router = APIRouter(prefix="/api/search", tags=["搜索"])


@router.get("/semantic")
async def semantic_search(
    query: str = Query(..., description="查询词", min_length=1, max_length=500),
    dataset_ids: Optional[str] = Query(None, description="知识库 ID 列表，逗号分隔"),
    top_k: int = Query(5, ge=1, le=100, description="返回数量"),
    dedup: bool = Query(True, description="是否启用智能去重"),
    dedup_threshold: float = Query(0.95, ge=0.0, le=1.0, description="去重相似度阈值"),
):
    """语义搜索接口 - 调用 RAGFlow 向量检索

    - **query**: 查询词
    - **dataset_ids**: 知识库 ID，逗号分隔，None 时使用默认知识库
    - **top_k**: 返回结果数量上限
    - **dedup**: 是否启用去重（默认开启，相似度>0.95 视为重复）
    - **dedup_threshold**: 去重阈值，范围 0.0~1.0

    Returns:
        JSON 包含 results 列表，每项包含 content, similarity, document_keyword 等
    """
    # 解析 dataset_ids
    kb_ids: Optional[List[str]] = None
    if dataset_ids:
        kb_ids = [d.strip() for d in dataset_ids.split(",") if d.strip()]

    service = get_ragflow_service()

    try:
        if dedup:
            chunks = await service.search_with_deduplication(
                query=query,
                dataset_ids=kb_ids,
                top_k=top_k,
                dedup_similarity=dedup_threshold,
            )
        else:
            chunks = await service.search_chunks(
                query=query,
                dataset_ids=kb_ids,
                top_k=top_k,
            )
    except Exception as e:
        logger.error(f"Semantic search error: {e}")
        return JSONResponse(
            status_code=500,
            content={"code": 1, "message": f"Search failed: {e}", "data": {"results": []}},
        )

    # 构建响应
    results = []
    for i, chunk in enumerate(chunks):
        results.append({
            "rank": i + 1,
            "chunk_id": chunk.get("id", ""),
            "content": chunk.get("content", ""),
            "document_id": chunk.get("document_id", ""),
            "document_keyword": chunk.get("document_keyword", ""),
            "dataset_id": chunk.get("dataset_id", ""),
            "similarity": round(chunk.get("similarity", 0), 4),
            "vector_similarity": round(chunk.get("vector_similarity", 0), 4),
            "term_similarity": round(chunk.get("term_similarity", 0), 4),
            "positions": chunk.get("positions", []),
        })

    return JSONResponse(content={
        "code": 0,
        "message": "success",
        "data": {
            "query": query,
            "total": len(results),
            "results": results,
        },
    })


@router.get("/datasets")
async def list_datasets():
    """获取可用知识库列表"""
    service = get_ragflow_service()
    try:
        datasets = await service.list_datasets()
    except Exception as e:
        logger.error(f"List datasets error: {e}")
        return JSONResponse(
            status_code=500,
            content={"code": 1, "message": str(e), "data": []},
        )

    cleaned = []
    for ds in datasets:
        cleaned.append({
            "id": ds.get("id", ""),
            "name": ds.get("name", ""),
            "chunk_count": ds.get("chunk_count", 0),
            "document_count": ds.get("document_count", 0),
            "status": ds.get("status", ""),
            "embedding_model": ds.get("embedding_model", ""),
        })

    return JSONResponse(content={
        "code": 0,
        "message": "success",
        "data": cleaned,
    })
