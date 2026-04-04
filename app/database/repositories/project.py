"""项目仓储"""

from typing import List, Optional

from .base import BaseRepository


class FavoriteRepository(BaseRepository):
    """收藏仓储"""

    def __init__(self):
        super().__init__(table_name="favorites")

    def add(self, project: dict) -> bool:
        """添加收藏"""
        return self.db.add_favorite(project)

    def add_sync(self, project: dict) -> bool:
        """同步添加收藏"""
        return self.db.add_favorite_sync(project)

    def remove(self, project_url: str) -> bool:
        """移除收藏"""
        return self.db.remove_favorite(project_url)

    def is_favorite(self, project_url: str) -> bool:
        """检查是否已收藏"""
        return self.db.is_favorite(project_url)

    def get_favorites(self, status: str = None, limit: int = 500) -> List[dict]:
        """获取收藏列表"""
        return self.db.get_favorites(status, limit)

    def update_status(self, project_url: str, status: str) -> bool:
        """更新收藏状态"""
        return self.db.update_favorite_status(project_url, status)

    def add_batch(self, projects: List[dict]) -> int:
        """批量添加收藏"""
        return self.db.add_favorites_batch(projects)


class AnnotationRepository(BaseRepository):
    """标注仓储"""

    def __init__(self):
        super().__init__(table_name="annotations")

    def add(self, project_url: str, note: str, priority: str = "normal", tags: list = None) -> bool:
        """添加标注"""
        return self.db.add_annotation(project_url, note, priority, tags)

    def get(self, project_url: str) -> Optional[dict]:
        """获取标注"""
        return self.db.get_annotation(project_url)

    def get_all(self, limit: int = 500) -> List[dict]:
        """获取所有标注"""
        return self.db.get_all_annotations(limit)

    def count(self) -> int:
        """获取标注数量"""
        return self.db.annotations_count()


class PresetRepository(BaseRepository):
    """预设仓储"""

    def __init__(self):
        super().__init__(table_name="filter_presets")

    def save(
        self, name: str, preset_key: str, filter_config: dict, is_default: bool = False
    ) -> bool:
        """保存预设"""
        return self.db.save_preset(name, preset_key, filter_config, is_default)

    def get(self, preset_key: str) -> Optional[dict]:
        """获取预设"""
        return self.db.get_preset(preset_key)

    def get_all(self) -> List[dict]:
        """获取所有预设"""
        return self.db.get_presets()

    def delete(self, preset_key: str) -> bool:
        """删除预设"""
        return self.db.delete_preset(preset_key)


class DuplicateRepository(BaseRepository):
    """重复记录仓储"""

    def __init__(self):
        super().__init__(table_name="duplicate_records")

    def add(
        self, canonical_url: str, duplicate_url: str, title: str = "", similarity: float = 0
    ) -> bool:
        """添加重复记录"""
        return self.db.add_duplicate(canonical_url, duplicate_url, title, similarity)

    def get_duplicates(self, canonical_url: str = None, limit: int = 200) -> List[dict]:
        """获取重复记录"""
        return self.db.get_duplicates(canonical_url, limit)


class LogRepository(BaseRepository):
    """日志仓储"""

    def __init__(self):
        super().__init__(table_name="scrape_logs")

    def add(self, level: str, message: str, source: str = "system") -> bool:
        """添加日志"""
        return self.db.add_log(level, message, source)

    def get_logs(self, level: str = None, limit: int = 200) -> List[dict]:
        """获取日志列表"""
        return self.db.get_logs(level, limit)

    def clear(self, before_days: int = 7) -> bool:
        """清理旧日志"""
        return self.db.clear_logs(before_days)


class CacheRepository(BaseRepository):
    """缓存仓储"""

    def __init__(self):
        super().__init__(table_name="data_cache")

    def get_cached(self, key: str) -> Optional[dict]:
        """获取缓存"""
        return self.db.get_cached(key)

    def set_cached(self, key: str, value: dict, ttl_seconds: int = 3600) -> bool:
        """设置缓存"""
        return self.db.set_cached(key, value, ttl_seconds)

    def invalidate(self, pattern: str = None) -> bool:
        """清除缓存"""
        return self.db.invalidate_cache(pattern)
