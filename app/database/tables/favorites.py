"""favorites 表操作"""

import queue
from typing import List

from loguru import logger


class FavoritesMixin:
    """favorites 表 CRUD 操作（混入 Database 类使用）"""

    def add_favorite(self, project: dict) -> bool:
        try:
            self._batch_queue.put(
                (
                    """INSERT OR REPLACE INTO favorites
                   (project_url, title, source_url, tender_type, budget, publish_date, updated_at)
                   VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    (
                        project.get("url", ""),
                        project.get("title", ""),
                        project.get("source_url", ""),
                        project.get("tender_type", ""),
                        project.get("budget", ""),
                        project.get("publish_date", ""),
                    ),
                )
            )
            return True
        except (queue.Full, OSError, IOError) as e:
            logger.error(f"add_favorite: {e}")
            return False

    def add_favorite_sync(self, project: dict) -> bool:
        try:
            with self._get_conn() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO favorites
                   (project_url, title, source_url, tender_type, budget, publish_date, updated_at)
                   VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    (
                        project.get("url", ""),
                        project.get("title", ""),
                        project.get("source_url", ""),
                        project.get("tender_type", ""),
                        project.get("budget", ""),
                        project.get("publish_date", ""),
                    ),
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"add_favorite_sync: {e}")
            return False

    def remove_favorite(self, project_url: str) -> bool:
        try:
            self._batch_queue.put(("DELETE FROM favorites WHERE project_url=?", (project_url,)))
            return True
        except (queue.Full, OSError) as e:
            logger.error(f"remove_favorite: {e}")
            return False

    def is_favorite(self, project_url: str) -> bool:
        try:
            c = self._get_conn()
            result = c.execute(
                "SELECT 1 FROM favorites WHERE project_url=?", (project_url,)
            ).fetchone()
            return result is not None
        except Exception as e:
            logger.error(f"is_favorite: {e}")
            return False

    def get_favorites(self, status: str = None, limit: int = 500) -> List[dict]:
        try:
            c = self._get_conn()
            if status:
                rows = c.execute(
                    """SELECT * FROM favorites WHERE status=?
                                   ORDER BY updated_at DESC LIMIT ?""",
                    (status, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM favorites ORDER BY updated_at DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_favorites: {e}")
            return []

    def update_favorite_status(self, project_url: str, status: str) -> bool:
        try:
            self._batch_queue.put(
                (
                    "UPDATE favorites SET status=?, updated_at=CURRENT_TIMESTAMP WHERE project_url=?",
                    (status, project_url),
                )
            )
            return True
        except (queue.Full, OSError) as e:
            logger.error(f"update_favorite_status: {e}")
            return False

    def add_favorites_batch(self, projects: List[dict]) -> int:
        if not projects:
            return 0
        count = 0
        conn = self._get_conn()
        try:
            conn.execute("BEGIN")
            for p in projects:
                conn.execute(
                    """INSERT OR IGNORE INTO favorites
                               (project_url, title, source_url, tender_type, budget, publish_date, updated_at)
                               VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    (
                        p.get("url", ""),
                        p.get("title", ""),
                        p.get("source_url", ""),
                        p.get("tender_type", ""),
                        p.get("budget", ""),
                        p.get("publish_date", ""),
                    ),
                )
                count += 1
            conn.execute("COMMIT")
        except Exception as e:
            conn.execute("ROLLBACK")
            logger.error(f"add_favorites_batch: {e}")
            return 0
        return count
