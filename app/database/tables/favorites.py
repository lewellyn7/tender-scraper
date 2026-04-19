"""favorites 表操作"""

import queue
from typing import List

from loguru import logger


class FavoritesMixin:
    """favorites 表 CRUD 操作（混入 Database 类使用）"""

    def add_favorite(self, project: dict, user_id: str = None) -> bool:
        try:
            self._batch_queue.put(
                (
                    """INSERT OR REPLACE INTO favorites
                   (user_id, project_url, title, source_url, tender_type, budget, publish_date, updated_at)
                   VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    (
                        user_id or "",
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

    def add_favorite_sync(self, project: dict, user_id: str = None) -> bool:
        try:
            with self._get_conn() as conn:
                conn.execute(
                    """INSERT INTO favorites
                   (user_id, project_url, title, source_url, tender_type, budget, publish_date, updated_at)
                   VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT (project_url) DO UPDATE SET
                   title=EXCLUDED.title, source_url=EXCLUDED.source_url,
                   tender_type=EXCLUDED.tender_type, budget=EXCLUDED.budget,
                   publish_date=EXCLUDED.publish_date, updated_at=CURRENT_TIMESTAMP""",
                    (
                        user_id or "",
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

    def remove_favorite(self, project_url: str, user_id: str = None) -> bool:
        try:
            if user_id:
                self._batch_queue.put(
                    ("DELETE FROM favorites WHERE project_url=? AND user_id=?", (project_url, user_id))
                )
            else:
                self._batch_queue.put(("DELETE FROM favorites WHERE project_url=?", (project_url,)))
            return True
        except (queue.Full, OSError) as e:
            logger.error(f"remove_favorite: {e}")
            return False

    def is_favorite(self, project_url: str, user_id: str = None) -> bool:
        try:
            c = self._get_conn()
            if user_id:
                result = c.execute(
                    "SELECT 1 FROM favorites WHERE project_url=? AND user_id=?", (project_url, user_id)
                ).fetchone()
            else:
                result = c.execute(
                    "SELECT 1 FROM favorites WHERE project_url=?", (project_url,)
                ).fetchone()
            return result is not None
        except Exception as e:
            logger.error(f"is_favorite: {e}")
            return False

    def get_favorites(self, user_id: str = None, status: str = None, limit: int = 500) -> List[dict]:
        try:
            c = self._get_conn()
            if user_id and status:
                rows = c.execute(
                    "SELECT * FROM favorites WHERE user_id=? AND status=? ORDER BY updated_at DESC LIMIT ?",
                    (user_id, status, limit),
                ).fetchall()
            elif user_id:
                rows = c.execute(
                    "SELECT * FROM favorites WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
            elif status:
                rows = c.execute(
                    "SELECT * FROM favorites WHERE status=? ORDER BY updated_at DESC LIMIT ?",
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

    def search_favorites(self, query: str, user_id: str = None, intent: str = None, limit: int = 20) -> List[dict]:
        """全文检索 favorites 表（支持 PG + SQLite）

        Args:
            query: 搜索关键词
            user_id: 可选，按用户过滤
            intent: 可选，按 tender_type 过滤（如 "招标公告", "中标结果"）
            limit: 返回数量上限
        """
        try:
            c = self._get_conn()
            like_pattern = f"%{query}%"
            if user_id and intent:
                sql = """SELECT * FROM favorites
                         WHERE user_id=? AND
                         (title LIKE ? OR tender_type LIKE ? OR budget LIKE ?)
                         AND tender_type = ?
                         ORDER BY updated_at DESC LIMIT ?"""
                rows = c.execute(sql, (user_id, like_pattern, like_pattern, like_pattern, intent, limit)).fetchall()
            elif user_id:
                sql = """SELECT * FROM favorites
                         WHERE user_id=? AND
                         (title LIKE ? OR tender_type LIKE ? OR budget LIKE ?)
                         ORDER BY updated_at DESC LIMIT ?"""
                rows = c.execute(sql, (user_id, like_pattern, like_pattern, like_pattern, limit)).fetchall()
            elif intent:
                sql = """SELECT * FROM favorites
                         WHERE (title LIKE ? OR tender_type LIKE ? OR budget LIKE ?)
                         AND tender_type = ?
                         ORDER BY updated_at DESC LIMIT ?"""
                rows = c.execute(sql, (like_pattern, like_pattern, like_pattern, intent, limit)).fetchall()
            else:
                sql = """SELECT * FROM favorites
                         WHERE title LIKE ? OR tender_type LIKE ? OR budget LIKE ?
                         ORDER BY updated_at DESC LIMIT ?"""
                rows = c.execute(sql, (like_pattern, like_pattern, like_pattern, limit)).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"search_favorites: {e}")
            return []

    def update_favorite_status(self, project_url: str, status: str, user_id: str = None) -> bool:
        try:
            if user_id:
                self._batch_queue.put(
                    (
                        "UPDATE favorites SET status=?, updated_at=CURRENT_TIMESTAMP WHERE project_url=? AND user_id=?",
                        (status, project_url, user_id),
                    )
                )
            else:
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

    def add_favorites_batch(self, projects: List[dict], user_id: str = None) -> int:
        if not projects:
            return 0
        count = 0
        conn = self._get_conn()
        try:
            conn.execute("BEGIN")
            for p in projects:
                conn.execute(
                    """INSERT INTO favorites
                               (user_id, project_url, title, source_url, tender_type, budget, publish_date, updated_at)
                               VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                               ON CONFLICT (project_url) DO NOTHING""",
                    (
                        user_id or "",
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
