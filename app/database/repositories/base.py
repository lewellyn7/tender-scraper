"""基础仓储类"""

from abc import ABC
from typing import Any, Dict, Generic, List, Optional, TypeVar

T = TypeVar("T")


class BaseRepository(ABC, Generic[T]):
    """数据仓储基类"""

    def __init__(self, table_name: str):
        from app.database import get_db

        self.db = get_db()
        self.conn = self.db._get_conn()
        self.table_name = table_name

    def get_all(self, limit: int = 100) -> List[Dict]:
        """获取所有记录"""
        rows = self.conn.execute(f"SELECT * FROM {self.table_name} LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_by_id(self, id_field: str, id_value: Any) -> Optional[Dict]:
        """根据 ID 获取单条记录"""
        row = self.conn.execute(
            f"SELECT * FROM {self.table_name} WHERE {id_field} = ?", (id_value,)
        ).fetchone()
        return dict(row) if row else None

    def count(self) -> int:
        """获取记录总数"""
        result = self.conn.execute(f"SELECT COUNT(*) FROM {self.table_name}").fetchone()
        return result[0] if result else 0

    def delete(self, id_field: str, id_value: Any) -> bool:
        """删除记录"""
        try:
            self.conn.execute(f"DELETE FROM {self.table_name} WHERE {id_field} = ?", (id_value,))
            self.conn.commit()
            return True
        except Exception as e:
            self.db.logger.error(f"Delete error: {e}")
            return False
