"""P0-4: 向量化模块 — 从 main.py 拆出
=========================================

负责:
- _build_vector_text: 构造用于 embedding 的拼接文本
- _upsert_to_vector_store: 批量 upsert 到 vector_store (失败不影响主流程)

原 main.py:41-86

变更 (2026-06-20):
- doc_id 从 `tender_{date}_{i}` 改为 `tender_{url_hash[:16]}` (sha256)
- 原因: 之前 doc_id 是 publish_date + index, 不可关联 projects_cqggzy.id
- 修复后: doc_id 与 reindex_vector_store / backfill_vectors_incremental 完全一致
- 代价: 现有 109K vector 需重建 (脚本 backfill_vectors_incremental.py 33min)
"""
import hashlib

from loguru import logger

from app.services.vector_store import get_vector_store_indexed


def _stable_doc_id(p: dict) -> str:
    """稳定的 doc_id — 基于 url 的 sha256 hash[:16]

    为什么不用 PG id?
    - vectorize 在 PG upsert 之前运行 (pipeline.py:453)
    - 采集阶段 std dict 没有 PG id
    - 用 url_hash 完全解耦, vectorize 与 backfill 两路一致

    边界:
    - url 为空 (极少): 用 hash(title) fallback
    - 同 url 多条记录: doc_id 重复, upsert_documents 会按 id 去重
    """
    url = p.get("url") or ""
    if url:
        return f"tender_{hashlib.sha256(url.encode()).hexdigest()[:16]}"
    fallback = p.get("title") or ""
    return f"tender_nourl_{hashlib.sha256(fallback.encode()).hexdigest()[:16]}"


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
    if not projects:
        return
    try:
        docs = [
            {
                "id": _stable_doc_id(p),
                "text": _build_vector_text(p),
                "metadata": {
                    "url": p.get("url"),
                    "title": p.get("title"),
                    "type": p.get("type"),
                    "business_type": p.get("business_type"),
                    "info_type": p.get("info_type"),
                    "budget": p.get("budget"),
                    "deadline": p.get("deadline"),
                    "region": p.get("region"),
                    "publish_date": p.get("publish_date"),
                    "keywords_matched": p.get("keywords_matched"),
                }
            }
            for p in projects
        ]
        vs = get_vector_store_indexed()
        result = vs.upsert_documents(docs)
        logger.info(f"向量入库: {result['inserted']} 条，backend={result['backend']}")
    except Exception as e:
        # 2026-06-20 修复: logger.warning 改为 logger.exception, 错误可见
        logger.exception(f"向量入库失败（不影响主流程）: {e}")