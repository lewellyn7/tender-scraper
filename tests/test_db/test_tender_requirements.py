"""get_tender_requirements 表查找优先级测试 (qualification-ai P0-1)

修复 2026-06-07: 旧实现查 favorites 表（错表，favorites 没有 bidder_requirements 列）。
新实现按 cqggzy → ccgp → favorites 优先级回退。

使用测试 PG (容器内) — 真实表结构。
"""
import pytest


@pytest.fixture
def pg_db():
    """复用容器内真实 PG 数据库。测试用临时数据，测试完清理。"""
    from app.database import get_db
    db = get_db()
    # 清理临时数据
    c = db._get_conn()
    c.execute("DELETE FROM projects_cqggzy WHERE title LIKE 'TEST_qual_ai_%'")
    c.execute("DELETE FROM projects_ccgp WHERE title LIKE 'TEST_qual_ai_%'")
    c.execute("DELETE FROM favorites WHERE title LIKE 'TEST_qual_ai_%'")
    c.commit()
    yield db
    # 测试后清理
    c = db._get_conn()
    c.execute("DELETE FROM projects_cqggzy WHERE title LIKE 'TEST_qual_ai_%'")
    c.execute("DELETE FROM projects_ccgp WHERE title LIKE 'TEST_qual_ai_%'")
    c.execute("DELETE FROM favorites WHERE title LIKE 'TEST_qual_ai_%'")
    c.commit()


class TestTenderRequirementsLookup:
    """测试 3 表 fallback 优先级"""

    def test_cqggzy_hit_returns_source_cqggzy(self, pg_db):
        """① cqggzy 命中 → source='projects_cqggzy'"""
        c = pg_db._get_conn()
        c.execute(
            "INSERT INTO projects_cqggzy (url, title, bidder_requirements, tender_type) "
            "VALUES (%s, %s, %s, %s)",
            ("https://test/cqggzy-1", "TEST_qual_ai_房建工程", "建筑工程施工总承包一级", "工程建设"),
        )
        c.commit()
        row = c.execute("SELECT id FROM projects_cqggzy WHERE url=%s",
                        ("https://test/cqggzy-1",)).fetchone()
        tid = row[0]

        result = pg_db.get_tender_requirements(tid)
        assert result is not None
        assert result["source"] == "projects_cqggzy"
        assert "建筑工程施工总承包一级" in result["requirements_text"]
        assert result["has_requirements"] is True

    def test_ccgp_hit_when_cqggzy_empty(self, pg_db):
        """② cqggzy 没有 → ccgp 命中 → source='projects_ccgp'"""
        c = pg_db._get_conn()
        c.execute(
            "INSERT INTO projects_ccgp (url, title, bidder_requirements) "
            "VALUES (%s, %s, %s)",
            ("https://test/ccgp-1", "TEST_qual_ai_政府采购项目", "信息系统集成二级"),
        )
        c.commit()
        row = c.execute("SELECT id FROM projects_ccgp WHERE url=%s",
                        ("https://test/ccgp-1",)).fetchone()
        tid = row[0]

        result = pg_db.get_tender_requirements(tid)
        assert result is not None
        assert result["source"] == "projects_ccgp"
        assert "信息系统集成二级" in result["requirements_text"]

    def test_favorites_fallback_when_both_empty(self, pg_db):
        """③ cqggzy/ccgp 都没有 → favorites 兜底"""
        c = pg_db._get_conn()
        c.execute(
            "INSERT INTO favorites (project_url, title, tender_type) "
            "VALUES (%s, %s, %s)",
            ("https://test/fav-1", "TEST_qual_ai_老项目", "政府采购"),
        )
        c.commit()
        row = c.execute("SELECT id FROM favorites WHERE project_url=%s",
                        ("https://test/fav-1",)).fetchone()
        tid = row[0]

        result = pg_db.get_tender_requirements(tid)
        assert result is not None
        assert result["source"] == "favorites"
        # favorites 无 bidder_requirements → fallback 到 tender_type
        assert result["requirements_text"] == "政府采购"
        assert result["has_requirements"] is False

    def test_cqggzy_takes_priority_over_ccgp(self, pg_db):
        """④ 两边都存在 → cqggzy 赢"""
        c = pg_db._get_conn()
        # 用非常大的 id 避免冲突
        c.execute(
            "INSERT INTO projects_cqggzy (url, title) VALUES (%s, %s)",
            ("https://test/dup-1", "TEST_qual_ai_dup_cqggzy"),
        )
        c.commit()
        cqggzy_id = c.execute("SELECT id FROM projects_cqggzy WHERE url=%s",
                              ("https://test/dup-1",)).fetchone()[0]
        c.execute(
            "INSERT INTO projects_ccgp (url, title) VALUES (%s, %s)",
            ("https://test/dup-1", "TEST_qual_ai_dup_ccgp"),
        )
        c.commit()
        ccgp_id = c.execute("SELECT id FROM projects_ccgp WHERE url=%s",
                            ("https://test/dup-1",)).fetchone()[0]

        # 用 cqggzy id 应该命中 cqggzy
        result = pg_db.get_tender_requirements(cqggzy_id)
        assert result["source"] == "projects_cqggzy"
        # 用 ccgp id 应该命中 ccgp
        result2 = pg_db.get_tender_requirements(ccgp_id)
        assert result2["source"] == "projects_ccgp"

    def test_not_found_returns_none(self, pg_db):
        """⑤ ID 不存在 → None"""
        result = pg_db.get_tender_requirements(999999999)
        assert result is None

    def test_empty_requirements_fallback_to_tender_type(self, pg_db):
        """⑥ bidder_requirements 为空 → 用 tender_type 兜底"""
        c = pg_db._get_conn()
        c.execute(
            "INSERT INTO projects_cqggzy (url, title, bidder_requirements, tender_type) "
            "VALUES (%s, %s, %s, %s)",
            ("https://test/empty-1", "TEST_qual_ai_兜底测试", "", "工程建设"),
        )
        c.commit()
        tid = c.execute("SELECT id FROM projects_cqggzy WHERE url=%s",
                        ("https://test/empty-1",)).fetchone()[0]

        result = pg_db.get_tender_requirements(tid)
        assert result["requirements_text"] == "工程建设"
        assert result["has_requirements"] is False

    def test_returns_metadata_fields(self, pg_db):
        """⑦ 返回 budget / region 等元数据"""
        c = pg_db._get_conn()
        c.execute(
            "INSERT INTO projects_cqggzy (url, title, bidder_requirements, budget, region) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("https://test/meta-1", "TEST_qual_ai_元数据测试", "市政三级", "500万", "重庆"),
        )
        c.commit()
        tid = c.execute("SELECT id FROM projects_cqggzy WHERE url=%s",
                        ("https://test/meta-1",)).fetchone()[0]

        result = pg_db.get_tender_requirements(tid)
        assert result["budget"] == "500万"
        assert result["region"] == "重庆"
