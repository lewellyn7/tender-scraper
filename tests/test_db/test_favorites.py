"""favorites 用户隔离测试"""

import pytest


@pytest.fixture
def sample_project():
    return {
        "url": "https://example.com/project/1",
        "title": "测试项目",
        "source_url": "https://example.com",
        "tender_type": "政府采购",
        "budget": "100万元",
        "publish_date": "2024-01-01",
    }


@pytest.fixture
def another_project():
    return {
        "url": "https://example.com/project/2",
        "title": "另一个项目",
        "source_url": "https://example.com",
        "tender_type": "工程建设",
        "budget": "200万元",
        "publish_date": "2024-01-02",
    }


class TestFavoritesUserIsolation:
    """用户隔离测试"""

    def test_same_url_different_users(self, test_db, sample_project):
        """同一URL可被不同用户分别收藏"""
        assert test_db.add_favorite_sync(sample_project, user_id="user_a") is True
        assert test_db.add_favorite_sync(sample_project, user_id="user_b") is True

        favs_a = test_db.get_favorites(user_id="user_a")
        favs_b = test_db.get_favorites(user_id="user_b")

        assert len(favs_a) == 1
        assert len(favs_b) == 1
        assert favs_a[0]["project_url"] == sample_project["url"]
        assert favs_b[0]["project_url"] == sample_project["url"]
        # 两条独立记录
        assert favs_a[0]["id"] != favs_b[0]["id"]

    def test_remove_only_affects_target_user(self, test_db, sample_project):
        """删除只影响指定用户的收藏"""
        test_db.add_favorite_sync(sample_project, user_id="user_a")
        test_db.add_favorite_sync(sample_project, user_id="user_b")

        test_db.remove_favorite(sample_project["url"], user_id="user_a")

        favs_a = test_db.get_favorites(user_id="user_a")
        favs_b = test_db.get_favorites(user_id="user_b")

        assert len(favs_a) == 0
        assert len(favs_b) == 1

    def test_is_favorite_respects_user(self, test_db, sample_project):
        """is_favorite 仅对有收藏的用户返回True"""
        test_db.add_favorite_sync(sample_project, user_id="user_a")

        assert test_db.is_favorite(sample_project["url"], user_id="user_a") is True
        assert test_db.is_favorite(sample_project["url"], user_id="user_b") is False

    def test_status_update_respects_user(self, test_db, sample_project):
        """状态更新仅影响指定用户"""
        test_db.add_favorite_sync(sample_project, user_id="user_a")
        test_db.add_favorite_sync(sample_project, user_id="user_b")

        test_db.update_favorite_status(sample_project["url"], "archived", user_id="user_a")

        fav_a = test_db.get_favorite(sample_project["url"], user_id="user_a")
        fav_b = test_db.get_favorite(sample_project["url"], user_id="user_b")

        assert fav_a["status"] == "archived"
        assert fav_b["status"] == "pending"

    def test_batch_respects_user(self, test_db, another_project):
        """批量添加正确隔离用户"""
        projects = [
            {**another_project, "url": "https://example.com/p1"},
            {**another_project, "url": "https://example.com/p2"},
        ]
        count = test_db.add_favorites_batch(projects, user_id="user_x")
        assert count == 2

        # user_y 未添加
        favs_y = test_db.get_favorites(user_id="user_y")
        assert len(favs_y) == 0

        favs_x = test_db.get_favorites(user_id="user_x")
        assert len(favs_x) == 2

    def test_get_favorite_returns_correct_user_record(self, test_db, sample_project):
        """get_favorite 返回指定用户的记录"""
        test_db.add_favorite_sync(sample_project, user_id="user_a")
        test_db.add_favorite_sync({**sample_project, "title": "modified"}, user_id="user_b")

        fav_a = test_db.get_favorite(sample_project["url"], user_id="user_a")
        fav_b = test_db.get_favorite(sample_project["url"], user_id="user_b")

        assert fav_a["title"] == "测试项目"
        assert fav_b["title"] == "modified"


class TestFavoritesCrud:
    """基础CRUD测试"""

    def test_add_and_get(self, test_db, sample_project):
        result = test_db.add_favorite_sync(sample_project)
        assert result is True
        favs = test_db.get_favorites()
        assert len(favs) == 1

    def test_remove(self, test_db, sample_project):
        test_db.add_favorite_sync(sample_project)
        result = test_db.remove_favorite(sample_project["url"])
        assert result is True
        assert len(test_db.get_favorites()) == 0

    def test_update_status(self, test_db, sample_project):
        test_db.add_favorite_sync(sample_project)
        test_db.update_favorite_status(sample_project["url"], "archived")
        fav = test_db.get_favorite(sample_project["url"])
        assert fav["status"] == "archived"

    def test_search(self, test_db, sample_project):
        test_db.add_favorite_sync(sample_project)
        results = test_db.search_favorites("测试")
        assert len(results) == 1
        assert results[0]["title"] == "测试项目"

    def test_pagination(self, test_db):
        for i in range(10):
            test_db.add_favorite_sync({
                "url": f"https://example.com/p{i}",
                "title": f"项目{i}",
                "source_url": "https://example.com",
                "tender_type": "政府采购",
                "budget": "100万元",
                "publish_date": "2024-01-01",
            })
        total = test_db.get_favorite_count()
        assert total == 10
        page1 = test_db.get_favorites(limit=3, offset=0)
        page2 = test_db.get_favorites(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 3
        assert page1[0]["title"] != page2[0]["title"]

    def test_filter_by_status(self, test_db, sample_project):
        test_db.add_favorite_sync(sample_project)
        test_db.update_favorite_status(sample_project["url"], "archived")
        active = test_db.get_favorites(status="pending")
        archived = test_db.get_favorites(status="archived")
        assert len(active) == 0
        assert len(archived) == 1
