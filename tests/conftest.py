import os
import queue
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

@pytest.fixture
def test_db():
    """使用内存数据库进行测试"""
    from app.database import Database
    # 创建临时内存数据库
    db = Database(":memory:")
    db._initialized = True  # 跳过初始化
    db._init_tables()
    yield db
    # 关闭前清空批处理队列
    try:
        while not db._batch_queue.empty():
            try:
                db._batch_queue.get_nowait()
            except queue.Empty:
                break
    except Exception:
        pass
    db.close()

@pytest.fixture
def sample_project():
    return {
        "url": "https://example.com/project/1",
        "title": "测试项目",
        "source_url": "https://example.com",
        "tender_type": "政府采购",
        "budget": "100万元",
        "publish_date": "2024-01-01"
    }


@pytest.fixture
def ragflow_mock(monkeypatch):
    """RAGFlow 检索 mock fixture — patch search_chunks + 设置 DATASET_ID"""
    from services.ragflow_service import RAGFlowService
    import services.ragflow_service as ragflow_module

    # 注入 DATASET_ID（避免 test 跳过）
    monkeypatch.setattr(ragflow_module, "DEFAULT_DATASET_ID", "test_dataset_id")

    async def mock_search(*args, **kwargs):
        return [
            {
                "id": "chunk_001",
                "content": "这是测试检索内容，涉及智慧城市建设。",
                "document_id": "doc_001",
                "document_keyword": "智慧城市方案.docx",
                "dataset_id": "test_dataset_id",
                "similarity": 4.2,
                "vector_similarity": 0.45,
                "term_similarity": 0.18,
            },
            {
                "id": "chunk_002",
                "content": "招标采购系统架构设计，包含前后端分离方案。",
                "document_id": "doc_002",
                "document_keyword": "系统架构设计.docx",
                "dataset_id": "test_dataset_id",
                "similarity": 3.8,
                "vector_similarity": 0.40,
                "term_similarity": 0.15,
            },
        ]

    monkeypatch.setattr(RAGFlowService, "search_chunks", mock_search)
    return mock_search
