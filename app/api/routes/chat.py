"""自然语言问答路由 - RAG 检索 + 结构化响应"""

from typing import Optional
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from loguru import logger

from services.ragflow_service import get_ragflow_service
from app.nlp.classifier import TenderClassifier
from app.nlp.summarizer import TextSummarizer

router = APIRouter(prefix="/api/chat", tags=["智能问答"])


# 全局单例
_classifier = TenderClassifier()
_summarizer = TextSummarizer()


# 意图关键词
INTENT_KEYWORDS = {
    "招标公告": ["招标公告", "招标", "采购公告", "招标信息", "招标项目"],
    "中标结果": ["中标", "成交", "结果公告", "中标人", "中标供应商", "成交人"],
    "资质要求": ["资质", "证书", "认证", "许可", "要求具备"],
    "预算金额": ["预算", "金额", "价格", "报价", "限价", "多少钱"],
    "时间节点": ["截止", "报名", "开标", "投标", "时间", "截止日期", "截止时间"],
    "采购需求": ["需求", "要求", "规格", "参数", "清单", "内容"],
    "联系方式": ["联系", "电话", "联系人", "邮箱", "地址", "怎么联系"],
}


def _detect_intent(query: str) -> str:
    """检测查询意图"""
    query_lower = query
    scores = {}
    for intent, keywords in INTENT_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in query_lower)
        if score > 0:
            scores[intent] = score
    return max(scores, key=scores.get) if scores else "招标公告"


@router.get("/ask")
async def ask(
    question: str = Query(..., description="自然语言问题", min_length=2, max_length=500),
    dataset_ids: Optional[str] = Query(None, description="知识库 ID，逗号分隔"),
    top_k: int = Query(3, ge=1, le=20, description="检索 chunk 数"),
):
    """
    自然语言问答接口
    1. 检索 RAGFlow 知识库
    2. 结构化提取关键信息
    3. 返回分类 + 摘要 + 原始 chunks
    """
    # 解析 dataset_ids
    kb_ids = None
    if dataset_ids:
        kb_ids = [d.strip() for d in dataset_ids.split(",") if d.strip()]

    # 意图检测
    intent = _detect_intent(question)

    # 检索知识库
    service = get_ragflow_service()
    try:
        chunks = await service.search_chunks(
            query=question,
            dataset_ids=kb_ids,
            top_k=top_k,
            similarity_threshold=0.1,
        )
    except Exception as e:
        logger.error(f"RAG search error: {e}")
        chunks = []

    # 提取关键信息
    all_text = "\n".join(c.get("content", "") for c in chunks)
    summary = _summarizer.summarize(all_text, max_sentences=3) if all_text else ""
    deadline = _summarizer.extract_deadline(all_text)
    budget = _summarizer.extract_budget(all_text)
    contact = _summarizer.extract_contact(all_text)

    # 对每个 chunk 做分类
    classified_chunks = []
    for i, chunk in enumerate(chunks):
        text = chunk.get("content", "")
        title = chunk.get("document_keyword", "")
        classification = _classifier.classify(title, text)
        classified_chunks.append({
            "rank": i + 1,
            "chunk_id": chunk.get("id", ""),
            "content": text[:500] + "..." if len(text) > 500 else text,
            "document_keyword": title,
            "similarity": round(chunk.get("similarity", 0), 4),
            "classification": classification,
        })

    return JSONResponse(content={
        "code": 0,
        "message": "success",
        "data": {
            "question": question,
            "intent": intent,
            "summary": summary,
            "deadline": deadline,
            "budget": budget,
            "contact": contact,
            "chunks": classified_chunks,
            "total": len(classified_chunks),
        },
    })


@router.get("/intent")
async def detect_intent(
    query: str = Query(..., description="查询文本", min_length=2, max_length=500),
):
    """意图检测接口"""
    intent = _detect_intent(query)
    classification = _classifier.classify(query)
    return JSONResponse(content={
        "code": 0,
        "data": {
            "query": query,
            "intent": intent,
            "classification": classification,
        },
    })


@router.get("/classify")
async def classify_text(
    title: str = Query(..., description="标题", max_length=500),
    content: str = Query("", description="正文（可选）", max_length=5000),
    budget: str = Query("", description="金额（可选）", max_length=100),
):
    """文本分类接口 - 返回类别/地域/优先级/关键词"""
    result = _classifier.classify(title, content, budget)
    return JSONResponse(content={
        "code": 0,
        "data": result,
    })
