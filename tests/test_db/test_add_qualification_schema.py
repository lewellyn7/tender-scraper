"""add_qualification schema 兼容性测试 (qualification-ai D-0)

修复 2026-06-07: 原代码 INSERT 引用了不存在的 notes/user_id 列。
生产 PG 实际只有 14 列，导致 add_qualification 永远失败。
新代码 INSERT 10 列与实际 schema 对齐。
"""
import pytest


@pytest.fixture
def pg_db():
    """复用容器内真实 PG。测试后清理测试数据。"""
    from app.database import get_db
    db = get_db()
    c = db._get_conn()
    c.execute("DELETE FROM bidder_qualifications WHERE name LIKE 'TEST_qual_ai_add_%'")
    c.commit()
    yield db
    c.execute("DELETE FROM bidder_qualifications WHERE name LIKE 'TEST_qual_ai_add_%'")
    c.commit()


class TestAddQualificationSchema:
    def test_basic_insert_returns_id(self, pg_db):
        """最简插入能拿到 id"""
        qid = pg_db.add_qualification({
            "name": "TEST_qual_ai_add_basic",
            "category": "建筑",
            "level": "一级",
        })
        assert qid is not None
        assert isinstance(qid, int)

    def test_full_fields_inserted(self, pg_db):
        """所有字段正确写入并可读回"""
        data = {
            "name": "TEST_qual_ai_add_full",
            "category": "建筑",
            "level": "一级",
            "certificate_no": "D1234567890",
            "valid_from": "2020-01-01",
            "valid_to": "2026-12-31",
            "issuer": "测试部",
            "file_path": "/tmp/test.pdf",
            "status": "有效",
        }
        qid = pg_db.add_qualification(data)
        assert qid is not None
        q = pg_db.get_qualification(qid)
        assert q["name"] == data["name"]
        assert q["category"] == "建筑"
        assert q["level"] == "一级"
        assert q["certificate_no"] == "D1234567890"
        assert q["status"] == "有效"

    def test_no_schema_drift_errors(self, pg_db):
        """不应再抛 'column does not exist'"""
        try:
            qid = pg_db.add_qualification({
                "name": "TEST_qual_ai_add_no_drift",
            })
            assert qid is not None
        except Exception as e:
            pytest.fail(f"add_qualification raised: {e}")

    def test_extra_fields_in_input_ignored(self, pg_db):
        """data 里多余字段（notes/user_id）应该被忽略而不是报错"""
        qid = pg_db.add_qualification({
            "name": "TEST_qual_ai_add_extra",
            "notes": "这个字段不该存在",  # 旧 bug 字段
            "user_id": "fake_user",        # 旧 bug 字段
        })
        assert qid is not None
        q = pg_db.get_qualification(qid)
        # notes/user_id 不会写入也不该读出
        assert q.get("name") == "TEST_qual_ai_add_extra"
