"""日志数据仓储"""

from typing import List

from app.database.repositories.base import BaseRepository


class LogRepository(BaseRepository):
    """日志数据仓储"""

    def __init__(self):
        super().__init__("scrape_logs")

    def add(self, level: str, message: str, source: str = "system") -> bool:
        """添加日志"""
        try:
            self.db._batch_queue.put(
                (
                    "INSERT INTO scrape_logs (log_level, message, source) VALUES (?,?,?)",
                    (level, message, source),
                )
            )
            return True
        except Exception:
            return False

    def get_all(self, level: str = None, limit: int = 200) -> List[dict]:
        """获取日志"""
        if level:
            rows = self.conn.execute(
                """SELECT * FROM scrape_logs WHERE log_level=?
                ORDER BY created_at DESC LIMIT ?""",
                (level, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM scrape_logs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count(self, level: str = None) -> int:
        """获取日志数量"""
        if level:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM scrape_logs WHERE log_level=?", (level,)
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) FROM scrape_logs").fetchone()
        return row[0] if row else 0
