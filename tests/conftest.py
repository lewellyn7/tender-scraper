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
