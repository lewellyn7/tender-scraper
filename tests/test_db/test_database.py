"""数据库模块测试"""

def test_create_and_get_user(test_db):
    user_id = test_db.create_user({
        "username": "testuser",
        "password_hash": "hash123",
        "password_salt": "salt123",
        "role": "viewer"
    })
    assert user_id is not None
    user = test_db.get_user_by_username("testuser")
    assert user["username"] == "testuser"

def test_get_user_not_found(test_db):
    user = test_db.get_user_by_username("nonexistent")
    assert user is None

def test_favorites_crud(test_db, sample_project):
    # 测试添加收藏
    result = test_db.add_favorite_sync(sample_project)
    assert result == True
    
    # 测试获取收藏
    favorites = test_db.get_favorites()
    assert len(favorites) == 1
    
    # 测试删除收藏
    result = test_db.remove_favorite(sample_project["url"])
    assert result == True

def test_add_favorites_batch(test_db, sample_project):
    projects = [sample_project.copy() for _ in range(3)]
    for i, p in enumerate(projects):
        p["url"] = f"https://example.com/project/{i}"
    count = test_db.add_favorites_batch(projects)
    assert count == 3

def test_annotations(test_db):
    test_db.add_annotation("https://example.com/1", "测试备注", "high", ["tag1"])
    # 强制刷新批处理队列
    batch = []
    while True:
        try:
            batch.append(test_db._batch_queue.get_nowait())
        except:
            break
    if batch:
        test_db._execute_batch(batch)
    annotation = test_db.get_annotation("https://example.com/1")
    assert annotation is not None
    assert annotation["note"] == "测试备注"

def test_presets(test_db):
    test_db.save_preset("测试预设", "test_preset", {"keyword": "test"})
    preset = test_db.get_preset("test_preset")
    assert preset is not None
    assert preset["name"] == "测试预设"

def test_stats(test_db):
    stats = test_db.get_stats()
    assert "favorites_count" in stats

def test_user_stats(test_db):
    stats = test_db.get_user_stats()
    assert stats["total"] >= 0
