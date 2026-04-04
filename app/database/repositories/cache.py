"""缓存数据仓储"""

import json
from typing import Any, Optional

from app.database.repositories.base import BaseRepository


class CacheRepository(BaseRepository):
    """缓存数据仓储"""

    def __init__(self):
        super().__init__("data_cache")

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        row = self.conn.execute(
            """SELECT cache_value FROM data_cache
            WHERE cache_key=? AND (expires_at IS NULL OR expires_at > datetime('now'))""",
            (key,),
        ).fetchone()
        if row:
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return row[0]
        return None

    def set(self, key: str, value: Any, ttl_seconds: int = 3600) -> bool:
        """设置缓存"""
        try:
            self.db._batch_queue.put(
                (
                    """INSERT OR REPLACE INTO data_cache
                    (cache_key, cache_value, expires_at)
                    VALUES (?,?,datetime('now', '+' || ? || ' seconds'))""",
                    (key, json.dumps(value, ensure_ascii=False), ttl_seconds),
                )
            )
            return True
        except Exception:
            return False

    def delete(self, key: str) -> bool:
        """删除缓存"""
        try:
            self.db._batch_queue.put(("DELETE FROM data_cache WHERE cache_key=?", (key,)))
            return True
        except Exception:
            return False
