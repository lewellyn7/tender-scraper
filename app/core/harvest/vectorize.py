"""P0-4: 向量化模块 — 从 main.py 拆出
=========================================

负责:
- _build_vector_text: 构造用于 embedding 的拼接文本
- _upsert_to_vector_store: 批量 upsert 到 vector_store (失败不影响主流程)

原 main.py:41-86
"""
from loguru import logger

from app.services.vector_store import get_vector_store_indexed


def _build_vector_text(p: dict) -> str:
    """构建用于向量化的文本（拼接多字段，控制长度）"""
    parts = [
        p.get("title", ""),
        p.get("type", ""),
        p.get("business_type", ""),
        p.get("info_type", ""),
        p.get("project_overview", ""),
        p.get("bidder_requirements", ""),
    ]
    # content_preview 含实际内容摘要，补充向量语义（尤其是 project_overview 为空时）
    content_preview = p.get("content_preview", "") or ""
    if content_preview:
        parts.append(content_preview[:500])
    text = " | ".join(x for x in parts if x)
    # MiniLM max_tokens=256, 约1000 tokens，截断至2000字符
    return text[:2000] if text else p.get("title", "")


def _upsert_to_vector_store(projects: list):
    """将采集结果批量入库向量库（失败不影响主流程）"""
    try:
        docs = [
            {
                "id": f"tender_{p.get('publish_date', 'unknown')}_{i}",
                "text": _build_vector_text(p),
                "metadata": {
                    "url": p.get("url"),
                    "title": p.get("title"),
                    "type": p.get("type"),
                    "budget": p.get("budget"),
                    "deadline": p.get("deadline"),
                    "region": p.get("region"),
                    "publish_date": p.get("publish_date"),
                    "keywords_matched": p.get("keywords_matched"),
                }
            }
            for i, p in enumerate(projects)
        ]
        vs = get_vector_store_indexed()
        result = vs.upsert_documents(docs)
        logger.info(f"向量入库: {result['inserted']} 条，backend={result['backend']}")
    except Exception as e:
        logger.warning(f"向量入库失败（不影响主流程）: {e}")
