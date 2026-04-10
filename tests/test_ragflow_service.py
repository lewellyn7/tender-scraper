"""
RAGFlow Service 测试
验证 RAGFlow API 连通性与基本功能
"""
import pytest
import asyncio
from services.ragflow_service import RAGFlowService, get_ragflow_service

class TestRAGFlowService:
    """RAGFlow 服务测试"""
    
    @pytest.fixture
    def service(self):
        return get_ragflow_service()
    
    def test_config_loaded(self):
        """配置已正确加载"""
        service = get_ragflow_service()
        assert service.base_url
        assert service.api_key
        assert "ragflow-" in service.api_key.lower()
    
    @pytest.mark.asyncio
    async def test_health_check(self, service):
        """健康检查"""
        healthy = await service.health_check()
        # 如果 RAGFlow 未运行，允许失败
        if not healthy:
            pytest.skip("RAGFlow service not available")
        assert healthy
    
    @pytest.mark.asyncio
    async def test_list_datasets(self, service):
        """获取知识库列表"""
        datasets = await service.list_datasets()
        # 至少能获取到响应
        assert isinstance(datasets, list)
        # 如果有数据集，验证结构
        if datasets:
            assert "id" in datasets[0]
            assert "name" in datasets[0]
    
    @pytest.mark.asyncio
    async def test_search_chunks(self, service, ragflow_mock):
        """语义检索测试（使用 mock，无需真实 RAGFlow）"""
        chunks = await service.search_chunks(
            query="测试",
            dataset_ids=["test_dataset_id"],
            top_k=3
        )
        assert isinstance(chunks, list)
        assert len(chunks) == 2
        assert chunks[0]["content"] == "这是测试检索内容，涉及智慧城市建设。"
        assert "similarity" in chunks[0]

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
