"""自然语言问答路由 - RAG 检索 + 数据库查询 + 结构化响应"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query, Body
from fastapi.responses import JSONResponse
from loguru import logger

from services.ragflow_service import get_ragflow_service
from app.api.dependencies import get_current_user
from app.database import get_db
from app.utils.log_sanitizer import sanitize_error_message
from app.nlp.classifier import TenderClassifier
from app.nlp.summarizer import TextSummarizer

router = APIRouter(prefix="/api/chat", tags=["智能问答"])


# 全局单例
_classifier = TenderClassifier()
_summarizer = TextSummarizer()


# 意图关键词
INTENT_KEYWORDS = {
    "招标公告": ["招标公告", "招标", "采购公告", "招标信息", "招标项目", "采购"],
    "中标结果": ["中标", "成交", "结果公告", "中标人", "中标供应商", "成交人", "结果"],
    "资质要求": ["资质", "证书", "认证", "许可", "要求具备", "资质要求"],
    "预算金额": ["预算", "金额", "价格", "报价", "限价", "多少钱", "预算金额"],
    "时间节点": ["截止", "报名", "开标", "投标", "时间", "截止日期", "截止时间", "何时"],
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


def _extract_field(field: str, text: str) -> str:
    """从文本中抽取指定字段"""
    if field == "budget":
        return _summarizer.extract_budget(text)
    elif field == "deadline":
        return _summarizer.extract_deadline(text)
    elif field == "contact":
        return _summarizer.extract_contact(text)
    return ""


def _build_result_item(row: Dict[str, Any], query: str, intent: str) -> Dict[str, Any]:
    """构建单条搜索结果"""
    title = row.get("title", "")
    tender_type = row.get("tender_type", "")
    budget = row.get("budget", "")
    source_url = row.get("source_url", "")
    project_url = row.get("project_url", "")
    publish_date = row.get("publish_date", "")
    status = row.get("status", "")
    
    # 组合全文用于摘要
    full_text = f"{title} {tender_type} {budget} {source_url}"
    
    # 抽取关键字段
    extracted_budget = _extract_field("budget", full_text) or budget
    extracted_deadline = _extract_field("deadline", full_text)
    extracted_contact = _extract_field("contact", full_text)
    
    # 来源判断
    source_name = "未知来源"
    if "ccgp" in source_url.lower():
        source_name = "政府采购网"
    elif "ggzy" in source_url.lower() or "cqggzy" in source_url.lower():
        source_name = "公共资源交易中心"
    elif "bidding" in source_url.lower():
        source_name = "招标投标平台"
    
    return {
        "title": title or "无标题",
        "tender_type": tender_type or "未分类",
        "budget": extracted_budget or budget or "未公示",
        "publish_date": publish_date or "未知",
        "source": source_name,
        "source_url": source_url,
        "project_url": project_url,
        "status": status,
        "intent_matched": intent,
    }


@router.get("/nl-query")
async def nl_query(
    q: str = Query(..., description="自然语言查询", min_length=2, max_length=500),
    intent_filter: Optional[str] = Query(None, description="按意图过滤"),
    limit: int = Query(10, ge=1, le=50, description="结果数量"),
    user_id: str = Depends(get_current_user)
):
    """
    自然语言查询接口 - 数据库检索 + LLM 摘要
    
    功能：
    1. 意图检测（招标公告/中标/资质要求/预算金额/时间节点/联系方式）
    2. 数据库全文检索 favorites 表
    3. LLM 智能摘要（优先）/规则抽取（降级）
    4. 返回结构化招标信息列表
    """
    # 1. 意图检测
    intent = _detect_intent(q)
    # intent_filter 仅当用户明确指定时才过滤 tender_type
    # 否则只用于显示，不限制搜索结果
    search_intent = intent_filter if intent_filter else None

    # 2. 数据库检索
    db = get_db()
    rows = db.search_favorites(query=q, intent=search_intent, limit=limit)

    # 3. 尝试 LLM 摘要（异步降级到规则）
    summary = ""
    try:
        from app.services.llm_service import get_llm_service
        svc = get_llm_service()
        if svc and svc._providers:
            prompt = (
                f"根据以下招标信息，生成50字以内的中文摘要：\n"
                f"{' | '.join(r.get('title', '') or r.get('tender_type', '') for r in rows[:5])}\n"
                f"问题：{q}"
            )
            result = await svc.chat(prompt=prompt, max_tokens=80)
            if result.success and result.content:
                summary = result.content.strip()
    except Exception as e:
        logger.debug(f"LLM summarization failed: {e}")

    # 4. 如果 LLM 失败，用规则生成摘要
    if not summary and rows:
        titles = [r.get("title", "") for r in rows[:3] if r.get("title")]
        if titles:
            summary = f"找到 {len(rows)} 条相关招标信息，包括：{'、'.join(titles[:2])}"

    # 5. 构建结果
    results = [_build_result_item(row, q, intent) for row in rows]

    return JSONResponse(content={
        "code": 0,
        "message": "success",
        "data": {
            "query": q,
            "intent": intent,
            "summary": summary or f"找到 {len(rows)} 条相关信息",
            "total": len(results),
            "results": results,
            "intent_label": _INTENT_LABELS.get(intent, intent),
        },
    })


# 意图中文标签
_INTENT_LABELS = {
    "招标公告": "招标公告",
    "中标结果": "中标结果",
    "资质要求": "资质要求",
    "预算金额": "预算金额",
    "时间节点": "时间节点",
    "采购需求": "采购需求",
    "联系方式": "联系方式",
}


@router.get("/ask")
async def ask(
    question: str = Query(..., description="自然语言问题", min_length=2, max_length=500),
    dataset_ids: Optional[str] = Query(None, description="知识库 ID，逗号分隔"),
    top_k: int = Query(3, ge=1, le=20, description="检索 chunk 数"),
    user_id: str = Depends(get_current_user)
):
    """
    自然语言问答接口
    1. 检索 RAGFlow 知识库
    2. 结构化提取关键信息
    3. 返回分类 + 摘要 + 原始 chunks
    """
    kb_ids = None
    if dataset_ids:
        kb_ids = [d.strip() for d in dataset_ids.split(",") if d.strip()]

    intent = _detect_intent(question)

    service = get_ragflow_service()
    try:
        chunks = await service.search_chunks(
            query=question,
            dataset_ids=kb_ids,
            top_k=top_k,
            similarity_threshold=0.1,
        )
    except Exception as e:
        logger.error(f"RAG search error: {sanitize_error_message(str(e))}")
        chunks = []

    all_text = "\n".join(c.get("content", "") for c in chunks)
    summary = _summarizer.summarize(all_text, max_sentences=3) if all_text else ""
    deadline = _summarizer.extract_deadline(all_text)
    budget = _summarizer.extract_budget(all_text)
    contact = _summarizer.extract_contact(all_text)

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
    user_id: str = Depends(get_current_user)
):
    """意图检测接口"""
    intent = _detect_intent(query)
    classification = _classifier.classify(query)
    return JSONResponse(content={
        "code": 0,
        "data": {
            "query": query,
            "intent": intent,
            "intent_label": _INTENT_LABELS.get(intent, intent),
            "classification": classification,
        },
    })


@router.get("/classify")
async def classify_text(
    title: str = Query(..., description="标题", max_length=500),
    content: str = Query("", description="正文（可选）", max_length=5000),
    budget: str = Query("", description="金额（可选）", max_length=100),
    user_id: str = Depends(get_current_user)
):
    """文本分类接口 - 返回类别/地域/优先级/关键词"""
    result = _classifier.classify(title, content, budget)
    return JSONResponse(content={
        "code": 0,
        "data": result,
    })
