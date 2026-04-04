"""重复记录数据仓储"""

from typing import List

from app.database.repositories.base import BaseRepository


class DuplicateRepository(BaseRepository):
    """重复记录数据仓储"""

    def __init__(self):
        super().__init__("duplicate_records")

    def add(
        self, canonical_url: str, duplicate_url: str, title: str = "", similarity: float = 0.0
    ) -> bool:
        """添加重复记录"""
        try:
            self.db._batch_queue.put(
                (
                    """INSERT OR IGNORE INTO duplicate_records
                    (canonical_url, duplicate_url, duplicate_title, similarity_score)
                    VALUES (?,?,?,?)""",
                    (canonical_url, duplicate_url, title, similarity),
                )
            )
            return True
        except Exception:
            return False

    def get_duplicates(self, canonical_url: str = None, limit: int = 200) -> List[dict]:
        """获取重复记录"""
        if canonical_url:
            rows = self.conn.execute(
                """SELECT * FROM duplicate_records WHERE canonical_url=?
                ORDER BY similarity_score DESC LIMIT ?""",
                (canonical_url, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM duplicate_records ORDER BY similarity_score DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        """获取重复记录数量"""
        row = self.conn.execute("SELECT COUNT(*) FROM duplicate_records").fetchone()
        return row[0] if row else 0
