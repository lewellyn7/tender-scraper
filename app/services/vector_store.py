"""VectorStoreService — 向量语义检索基础设施

支持多种后端：
  - numpy   : 纯 NumPy 实现（轻量 fallback，无需额外依赖）
  - chromadb: ChromaDB（生产推荐，需 pip install chromadb）
  - qdrant  : Qdrant（需 pip install qdrant-client）

配置方式（环境变量）：
  VECTOR_STORE_BACKEND=numpy|chromadb|qdrant
  EMBEDDING_MODEL=all-MiniLM-L6-v2   # HuggingFace sentence-transformers 模型名
  OPENAI_API_KEY=sk-...               # 如使用 OpenAI Embedding
  QDRANT_URL=http://localhost:6333
  QDRANT_API_KEY=...
"""

import hashlib
import os
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

BACKEND = os.getenv("VECTOR_STORE_BACKEND", "numpy").lower()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# ── Embedding Provider ─────────────────────────────────────

def _load_embedding_model():
    """延迟加载 embedding 模型（使用 vLLM 部署的 Qwen3-Embedding-4B）"""
    try:
        import httpx
        base_url = os.getenv("VLLM_EMBEDDING_URL", "http://host.docker.internal:8000/v1/embeddings")
        model_name = os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-4B")
        logger.info(f"[vector] Using vLLM embedding: {base_url} / {model_name}")
        return {"type": "vllm", "url": base_url, "model": model_name}
    except Exception as e:
        logger.warning(f"[vector] vLLM embedding init failed: {e}")
        return None


_embedding_model: Optional[Any] = None
_http_client: Optional[Any] = None
_text_embedding_cache: OrderedDict = OrderedDict()  # LRU cache for encoded texts
TEXT_CACHE_SIZE = 1000  # 最多缓存 1000 条文本向量


def _get_http_client() -> Any:
    """单例 HTTP 客户端（连接池复用）"""
    global _http_client
    if _http_client is None:
        import httpx
        _http_client = httpx.Client(
            timeout=30.0,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        logger.info("[vector] HTTP client pool initialized: max_conn=20")
    return _http_client


def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = _load_embedding_model()
    return _embedding_model


def encode_texts(texts: List[str]) -> List[List[float]]:
    """
    将文本列表转为向量列表（vLLM Embedding API，连接池复用）。

    优化点：
    1. httpx.Client 单例连接池（max_connections=20）
    2. 重试 3 次（指数退避），应对网络抖动
    3. 内存 LRU 缓存（TEXT_CACHE_SIZE 条），同文本不重复调用 vLLM
    4. TF-IDF fallback（vLLM 完全不可用时，避免返回随机向量
    """
    model = get_embedding_model()
    if model and isinstance(model, dict) and model.get('type') == 'vllm':
        # 先查缓存
        uncached: List[tuple[int, str]] = []
        cached_results: List[Optional[List[float]]] = [None] * len(texts)

        for i, text in enumerate(texts):
            cache_key = _text_cache_key(text)
            cached = _text_embedding_cache.get(cache_key)
            if cached is not None:
                cached_results[i] = cached
            else:
                uncached.append((i, text))

        if not uncached:
            logger.debug(f'[vector] encode_texts cache hit: {len(texts)}/{len(texts)}')
            return cached_results

        # 批量 encode 未缓存的文本
        uncached_texts = [t for _, t in uncached]
        for attempt in range(3):
            try:
                client = _get_http_client()
                response = client.post(
                    model['url'],
                    json={'input': uncached_texts, 'model': model['model']},
                )
                response.raise_for_status()
                data = response.json()
                embeddings = [item['embedding'] for item in data['data']]

                # 写入缓存（LRU 淘汰）
                for (i, text), emb in zip(uncached, embeddings):
                    cache_key = _text_cache_key(text)
                    _text_embedding_cache[cache_key] = emb
                    cached_results[i] = emb

                # LRU 淘汰超出容量
                while len(_text_embedding_cache) > TEXT_CACHE_SIZE:
                    _text_embedding_cache.popitem(last=False)

                logger.debug(f'[vector] Encoded {len(uncached_texts)} texts via vLLM (attempt {attempt+1})')
                return cached_results

            except Exception as e:
                wait = (2 ** attempt) * 0.5
                logger.warning(f'[vector] vLLM encoding failed (attempt {attempt+1}/3): {e}, retry in {wait}s')
                if attempt < 2:
                    time.sleep(wait)

        # 全部重试失败 → TF-IDF fallback（保证返回有用向量）
        logger.warning('[vector] vLLM unavailable after 3 attempts, using TF-IDF fallback')
        fallback_vecs = _tfidf_fallback(uncached_texts)
        for (i, _), fv in zip(uncached, fallback_vecs):
            cached_results[i] = fv
        return cached_results

    # 无 vLLM → TF-IDF fallback
    return _tfidf_fallback(texts)


# ── TF-IDF Fallback（vLLM 不可用时保底）────────────────────

_tfidf_cache: OrderedDict = OrderedDict()


def _text_cache_key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def _tfidf_fallback(texts: List[str]) -> List[List[float]]:
    """
    TF-IDF 向量 fallback（vLLM 完全不可用时使用）。
    基于字符 n-gram TF-IDF，保证向量有语义区分度（非随机）。
    """
    global _tfidf_cache
    dim = 256  # 降维维度
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        # 简单的字符级 n-gram
        vectorizer = TfidfVectorizer(analyzer='char', ngram_range=(2, 4), max_features=dim)
        tfidf_matrix = vectorizer.fit_transform(texts)
        # L2 normalize
        norms = (tfidf_matrix.multiply(tfidf_matrix)).sum(axis=1) ** 0.5
        norms[norms == 0] = 1
        normalized = tfidf_matrix.multiply(1 / norms)
        return normalized.toarray().tolist()
    except Exception as e:
        logger.warning(f'[vector] TF-IDF fallback also failed: {e}, using deterministic vectors')
        # 最差情况：基于文本内容的确定性向量（不是随机）
        import hashlib
        result = []
        for text in texts:
            h = int(hashlib.sha256(text.encode()).hexdigest(), 16)
            vec = [(h >> (i * 4)) & 0xFFFF for i in range(dim)]
            norm = sum(v * v for v in vec) ** 0.5 or 1
            result.append([v / norm for v in vec])
        return result


def cosine_sim(a: List[float], b: List[float]) -> float:
    """计算两个向量的余弦相似度"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    return dot / (norm_a * norm_b + 1e-9)


# ── 抽象后端接口 ─────────────────────────────────────────

class VectorBackend(ABC):
    """向量数据库抽象接口"""

    @abstractmethod
    def upsert(self, ids: List[str], embeddings: List[List[float]], payloads: List[Dict]):
        """插入或更新向量"""
        ...

    @abstractmethod
    def search(self, query_embedding: List[float], top_k: int = 5, filters: Optional[Dict] = None) -> List[Dict]:
        """向量相似度检索"""
        ...

    @abstractmethod
    def delete(self, ids: List[str]):
        """删除向量"""
        ...

    @abstractmethod
    def count(self) -> int:
        """返回向量总数"""
        ...


# ── NumPy Fallback 后端 ──────────────────────────────────

class NumpyVectorBackend(VectorBackend):
    """
    纯 NumPy 向量后端（无需额外依赖）

    适用场景：开发测试、小规模数据（<10 万条）
    缺点：无持久化、无分布式索引
    """

    def __init__(self, dim: int = 384):
        import numpy as np
        self._vectors: Dict[str, Tuple[List[float], Dict]] = {}
        self._dim = dim

    def upsert(self, ids: List[str], embeddings: List[List[float]], payloads: List[Dict]):
        for id_, emb, payload in zip(ids, embeddings, payloads):
            self._vectors[id_] = (emb, payload)
        logger.debug(f"[vector:numpy] upserted {len(ids)} vectors, total={len(self._vectors)}")

    def search(self, query_embedding: List[float], top_k: int = 5, filters: Optional[Dict] = None) -> List[Dict]:
        results = []
        for id_, (emb, payload) in self._vectors.items():
            sim = cosine_sim(query_embedding, emb)
            # 简单标签过滤
            if filters:
                match = all(payload.get(k) == v for k, v in filters.items())
                if not match:
                    continue
            results.append({"id": id_, "score": sim, **payload})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def delete(self, ids: List[str]):
        for id_ in ids:
            self._vectors.pop(id_, None)

    def count(self) -> int:
        return len(self._vectors)


# ── ChromaDB 后端 ────────────────────────────────────────

class ChromaDBBackend(VectorBackend):
    """ChromaDB 向量后端"""

    def __init__(self, collection_name: str = "tender_documents", dim: int = 384):
        import chromadb
        self._client = chromadb.PersistentClient(path="./data/chromadb")
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self._dim = dim
        logger.info(f"[vector:chroma] collection={collection_name} dim={dim}")

    def upsert(self, ids: List[str], embeddings: List[List[float]], payloads: List[Dict]):
        # ChromaDB upsert with payloads as metadatas
        flat_payloads = []
        for p in payloads:
            flat = {}
            for k, v in p.items():
                if isinstance(v, (str, int, float, bool)):
                    flat[k] = v
                else:
                    flat[k] = str(v)
            flat_payloads.append(flat)
        self._collection.upsert(ids=ids, embeddings=embeddings, metadatas=flat_payloads)

    def search(self, query_embedding: List[float], top_k: int = 5, filters: Optional[Dict] = None) -> List[Dict]:
        where = filters if filters else None
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
        )
        ids = results["ids"][0]
        dists = results["distances"][0] if "distances" in results else [0.0] * len(ids)
        metas = results["metadatas"][0] if "metadatas" in results else [{}] * len(ids)
        return [
            {"id": id_, "score": 1.0 - dist, **meta}
            for id_, dist, meta in zip(ids, dists, metas)
        ]

    def delete(self, ids: List[str]):
        self._collection.delete(ids=ids)

    def count(self) -> int:
        return self._collection.count()


# ── Qdrant 后端 ─────────────────────────────────────────

class QdrantBackend(VectorBackend):
    """Qdrant 向量后端"""

    def __init__(self, collection_name: str = "tender_documents", dim: int = 384):
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams
        self._client = QdrantClient(
            url=os.getenv("QDRANT_URL", "http://localhost:6333"),
            api_key=os.getenv("QDRANT_API_KEY", ""),
        )
        self._collection = collection_name
        self._dim = dim
        try:
            self._client.get_collection(collection_name)
        except Exception:
            self._client.create_collection(
                collection_name,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
        logger.info(f"[vector:qdrant] collection={collection_name} dim={dim}")

    def upsert(self, ids: List[str], embeddings: List[List[float]], payloads: List[Dict]):
        from qdrant_client.models import PointStruct
        points = [
            PointStruct(id=id_, vector=emb, payload=payload)
            for id_, emb, payload in zip(ids, embeddings, payloads)
        ]
        self._client.upsert(collection_name=self._collection, points=points)

    def search(self, query_embedding: List[float], top_k: int = 5, filters: Optional[Dict] = None) -> List[Dict]:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        query_filter = None
        if filters:
            query_filter = Filter(
                must=[
                    FieldCondition(key=k, match=MatchValue(value=v))
                    for k, v in filters.items()
                ]
            )
        results = self._client.search(
            collection_name=self._collection,
            query_vector=query_embedding,
            limit=top_k,
            query_filter=query_filter,
        )
        return [
            {"id": r.id, "score": r.score, **r.payload}
            for r in results
        ]

    def delete(self, ids: List[str]):
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        self._client.delete(
            collection_name=self._collection,
            points_selector=Filter(
                must=[FieldCondition(key="id", match=MatchValue(value=id_)) for id_ in ids]
            ) if ids else None,
        )

    def count(self) -> int:
        info = self._client.get_collection(self._collection)
        return info.vectors_count


# ── 后端工厂 ─────────────────────────────────────────────

_backend: Optional[VectorBackend] = None


def get_vector_backend() -> VectorBackend:
    global _backend
    if _backend is not None:
        return _backend

    dim = 384  # 标准 embedding 维度

    if BACKEND == "chromadb":
        try:
            _backend = ChromaDBBackend(dim=dim)
            logger.info("[vector] Using ChromaDB backend")
        except ImportError:
            logger.warning("[vector] ChromaDB not installed, falling back to numpy")
            _backend = NumpyVectorBackend(dim=dim)
    elif BACKEND == "qdrant":
        try:
            _backend = QdrantBackend(dim=dim)
            logger.info("[vector] Using Qdrant backend")
        except ImportError:
            logger.warning("[vector] Qdrant not installed, falling back to numpy")
            _backend = NumpyVectorBackend(dim=dim)
    else:
        _backend = NumpyVectorBackend(dim=dim)
        logger.info("[vector] Using NumPy backend (no external deps)")

    return _backend


# ── 主服务类 ─────────────────────────────────────────────

@dataclass
class SearchResult:
    id: str
    score: float
    payload: Dict


class VectorStoreService:
    """
    向量语义检索服务

    支持：
    - upsert: 批量添加/更新文档向量
    - search: 语义相似度检索
    - delete: 删除向量
    """

    def __init__(self):
        self._backend = get_vector_backend()

    def upsert_documents(self, docs: List[Dict]) -> Dict[str, Any]:
        """
        批量添加/更新文档

        docs: List[Dict], 每项需包含:
          - id: str（唯一标识）
          - text: str（待向量化的文本）
          - metadata: dict（附加元数据，如 source, title, created_at 等）
        """
        if not docs:
            return {"inserted": 0}

        texts = [d["text"] for d in docs]
        ids = [d["id"] for d in docs]
        payloads = [d.get("metadata", {}) for d in docs]

        # 向量化（批量一次请求）
        t0 = time.time()
        embeddings = encode_texts(texts)
        logger.debug(f"[vector] encoded {len(texts)} texts in {(time.time()-t0)*1000:.0f}ms")

        self._backend.upsert(ids, embeddings, payloads)

        return {"inserted": len(docs), "backend": BACKEND}

    def search(self, query: str, top_k: int = 5, filters: Optional[Dict] = None) -> List[Dict]:
        """
        语义检索

        query: 自然语言查询
        top_k: 返回数量
        filters: metadata 过滤条件（如 {"source": "ccgp"}）
        """
        t0 = time.time()
        query_emb = encode_texts([query])[0]
        raw = self._backend.search(query_emb, top_k=top_k, filters=filters)
        elapsed_ms = (time.time() - t0) * 1000

        results = []
        for r in raw:
            results.append({
                "id": r["id"],
                "score": round(r["score"], 4),
                "text": r.get("text", r.get("content", "")),
                "metadata": {k: v for k, v in r.items() if k not in ("id", "score", "text")},
            })

        logger.debug(f"[vector] search '{query[:30]}' -> {len(results)} results in {elapsed_ms:.0f}ms")
        return results

    def delete(self, ids: List[str]) -> Dict:
        self._backend.delete(ids)
        return {"deleted": len(ids)}

    def stats(self) -> Dict:
        return {
            "backend": BACKEND,
            "embedding_model": EMBEDDING_MODEL,
            "total_vectors": self._backend.count(),
        }


# ── 全局单例 ─────────────────────────────────────────────
_vector_service: Optional[VectorStoreService] = None


def get_vector_store() -> VectorStoreService:
    global _vector_service
    if _vector_service is None:
        _vector_service = VectorStoreService()
    return _vector_service
