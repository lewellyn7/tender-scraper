"""收藏数据仓储"""

from typing import List

from app.database.repositories.base import BaseRepository


class FavoriteRepository(BaseRepository):
    """收藏数据仓储"""

    def __init__(self):
        super().__init__("favorites")

    def add(self, project: dict) -> bool:
        """添加收藏"""
        self.db._batch_queue.put(
            (
                """INSERT OR REPLACE INTO favorites
                (project_url, title, source_url, tender_type, budget,
                 publish_date, updated_at)
                VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                (
                    project.get("project_url"),
                    project.get("title"),
                    project.get("source_url", ""),
                    project.get("tender_type", ""),
                    project.get("budget", ""),
                    project.get("publish_date", ""),
                ),
            )
        )
        return True

    def add_sync(self, project: dict) -> bool:
        """同步添加收藏"""
        try:
            with self.db._get_conn() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO favorites
                    (project_url, title, source_url, tender_type,
                     budget, publish_date, updated_at)
                    VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    (
                        project.get("project_url"),
                        project.get("title"),
                        project.get("source_url", ""),
                        project.get("tender_type", ""),
                        project.get("budget", ""),
                        project.get("publish_date", ""),
                    ),
                )
                return True
        except Exception as e:
            self.db.logger.error(f"add_favorite_sync: {e}")
            return False

    def remove(self, project_url: str) -> bool:
        """移除收藏"""
        try:
            self.db._batch_queue.put(
                ("DELETE FROM favorites WHERE project_url = ?", (project_url,))
            )
            return True
        except Exception as e:
            self.db.logger.error(f"remove_favorite: {e}")
            return False

    def exists(self, project_url: str) -> bool:
        """检查收藏是否存在"""
        row = self.conn.execute(
            "SELECT 1 FROM favorites WHERE project_url = ?", (project_url,)
        ).fetchone()
        return row is not None

    def get_all(self, status: str = None, limit: int = 500) -> List[dict]:
        """获取所有收藏"""
        if status:
            rows = self.conn.execute(
                """SELECT * FROM favorites WHERE status=?
                ORDER BY updated_at DESC LIMIT ?""",
                (status, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM favorites ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_status(self, project_url: str, status: str) -> bool:
        """更新收藏状态"""
        try:
            self.db._batch_queue.put(
                (
                    "UPDATE favorites SET status=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE project_url=?",
                    (status, project_url),
                )
            )
            return True
        except Exception as e:
            self.db.logger.error(f"update_favorite_status: {e}")
            return False

    def batch_add(self, projects: List[dict]) -> int:
        """批量添加收藏"""
        count = 0
        with self.db._get_conn() as conn:
            for p in projects:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO favorites
                        (project_url, title, source_url, tender_type,
                         budget, publish_date, updated_at)
                         VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                        (
                            p.get("project_url"),
                            p.get("title"),
                            p.get("source_url", ""),
                            p.get("tender_type", ""),
                            p.get("budget", ""),
                            p.get("publish_date", ""),
                        ),
                    )
                    count += 1
                except Exception:
                    pass
        return count

    def count(self, status: str = None) -> int:
        """获取收藏数量"""
        if status:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM favorites WHERE status=?", (status,)
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) FROM favorites").fetchone()
        return row[0] if row else 0

    def search(self, keyword: str, limit: int = 100) -> List[dict]:
        """搜索收藏"""
        rows = self.conn.execute(
            """SELECT * FROM favorites
            WHERE title LIKE ? OR description LIKE ?
            ORDER BY updated_at DESC LIMIT ?""",
            (f"%{keyword}%", f"%{keyword}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]
