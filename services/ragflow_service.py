"""
RAGFlow Service - 封装 RAGFlow MCP 与 HTTP API 调用
支持语义检索、文档上传、知识库管理
"""
import os
import httpx
from typing import List, Dict, Any, Optional
from loguru import logger
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

# ── 配置 ────────────────────────────────────────────────
RAGFLOW_MCP_URL = os.getenv("RAGFLOW_MCP_URL", "http://host.docker.internal:9382")
RAGFLOW_BASE_URL = os.getenv("RAGFLOW_BASE_URL", "http://host.docker.internal:8088")
RAGFLOW_API_KEY = os.getenv("RAGFLOW_API_KEY", "")
DEFAULT_DATASET_ID = os.getenv("RAGFLOW_DATASET_ID", "")

# ── HTTP 客户端 ──────────────────────────────────────────
_http_client: Optional[httpx.AsyncClient] = None

def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            headers={"Authorization": f"Bearer {RAGFLOW_API_KEY}", "Content-Type": "application/json"}
        )
    return _http_client

async def close_http_client():
    global _http_client
    if _http_client:
        await _http_client.aclose()
        _http_client = None

# ── RAGFlowService ──────────────────────────────────────
class RAGFlowService:
    """RAGFlow 服务封装 - 优先使用 HTTP API (MCP 模式待扩展)"""
    
    def __init__(self, base_url: str = None, api_key: str = None):
        self.base_url = base_url or RAGFLOW_BASE_URL
        self.api_key = api_key or RAGFLOW_API_KEY
        self.client = get_http_client()
    
    async def search_chunks(
        self,
        query: str,
        dataset_ids: List[str] = None,
        top_k: int = 5,
        similarity_threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """语义检索 - 返回 chunks（已按 similarity 降序）

        Args:
            query: 查询词
            dataset_ids: 知识库 ID 列表，None 时使用 DEFAULT_DATASET_ID
            top_k: 返回数量上限
            similarity_threshold: 最低相似度阈值（0.0-1.0），过滤低质量结果

        Returns:
            List[Dict]: chunk 列表，每项包含 content, similarity, document_keyword 等
        """
        if not dataset_ids:
            dataset_ids = [DEFAULT_DATASET_ID] if DEFAULT_DATASET_ID else []

        if not dataset_ids:
            logger.warning("No dataset_ids provided and DEFAULT_DATASET_ID not set")
            return []

        url = f"{self.base_url}/api/v1/retrieval"
        payload = {
            "question": query,           # RAGFlow API 使用 question 而非 query
            "dataset_ids": dataset_ids,
            "top_k": top_k,
        }

        try:
            resp = await self.client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                logger.warning(f"RAGFlow API error: {data.get('message', data)}")
                return []

            chunks = data.get("data", {}).get("chunks", [])

            # 按相似度降序排列
            chunks.sort(key=lambda x: x.get("similarity", 0), reverse=True)

            # 过滤低相似度结果
            if similarity_threshold > 0:
                chunks = [c for c in chunks if c.get("similarity", 0) >= similarity_threshold]

            return chunks

        except httpx.HTTPStatusError as e:
            logger.error(f"RAGFlow HTTP error {e.response.status_code}: {e.response.text}")
            return []
        except Exception as e:
            logger.error(f"RAGFlow search failed: {e}")
            return []

    async def search_with_deduplication(
        self,
        query: str,
        dataset_ids: List[str] = None,
        top_k: int = 10,
        dedup_similarity: float = 0.95,
    ) -> List[Dict[str, Any]]:
        """语义检索 + 智能去重

        Args:
            query: 查询词
            dataset_ids: 知识库 ID 列表
            top_k: 返回数量上限（去重前）
            dedup_similarity: 去重阈值（0.0-1.0），默认 0.95 视为重复

        Returns:
            List[Dict]: 去重后的 chunk 列表
        """
        # 扩大检索范围以提高去重效果
        raw_chunks = await self.search_chunks(
            query=query,
            dataset_ids=dataset_ids,
            top_k=top_k * 3,  # 预留更多候选
        )

        if not raw_chunks:
            return []

        # 按 document_keyword + 相似度分桶，保留每组最高相似度
        seen_docs: Dict[str, Dict[str, Any]] = {}

        for chunk in raw_chunks:
            doc_key = chunk.get("document_keyword", "")
            sim = chunk.get("similarity", 0)

            if doc_key not in seen_docs:
                seen_docs[doc_key] = chunk
            else:
                # 同一文档取相似度最高的那条
                if sim > seen_docs[doc_key].get("similarity", 0):
                    seen_docs[doc_key] = chunk

        # 再对不同文档按相似度去重（基于 vector_similarity）
        result: List[Dict[str, Any]] = []
        for chunk in sorted(seen_docs.values(), key=lambda x: x.get("similarity", 0), reverse=True):
            is_duplicate = False
            for kept in result:
                # 用 term_similarity 近似判断内容重复度
                ts = kept.get("term_similarity", 0)
                vs = kept.get("vector_similarity", 0)
                # 综合相似度（与 RAGFlow 内部权重一致: 0.7*vector + 0.3*term）
                combined = 0.7 * vs + 0.3 * ts
                if combined >= dedup_similarity:
                    is_duplicate = True
                    break

            if not is_duplicate:
                result.append(chunk)

            if len(result) >= top_k:
                break

        return result
    
    async def upload_document(
        self, 
        dataset_id: str, 
        file_path: str, 
        file_name: str
    ) -> Optional[str]:
        """上传文档到知识库 - 返回 document_id"""
        url = f"{self.base_url}/api/v1/dataset/{dataset_id}/document"
        try:
            with open(file_path, 'rb') as f:
                files = {'file': (file_name, f)}
                resp = await self.client.post(url, files=files)
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", {}).get("document_id")
        except Exception as e:
            logger.error(f"RAGFlow upload failed: {e}")
            return None
    
    async def list_datasets(self) -> List[Dict[str, Any]]:
        """获取知识库列表"""
        url = f"{self.base_url}/api/v1/datasets"
        try:
            resp = await self.client.get(url)
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", [])
        except Exception as e:
            logger.error(f"RAGFlow list datasets failed: {e}")
            return []
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            # RAGFlow 根路径返回 HTML 即表示服务正常
            resp = await self.client.get(self.base_url, timeout=httpx.Timeout(5.0))
            return resp.status_code == 200 and ('<div id="root"' in resp.text)
        except:
            return False

# ── 单例 ────────────────────────────────────────────────
_ragflow_service: Optional[RAGFlowService] = None

def get_ragflow_service() -> RAGFlowService:
    global _ragflow_service
    if _ragflow_service is None:
        _ragflow_service = RAGFlowService()
    return _ragflow_service
