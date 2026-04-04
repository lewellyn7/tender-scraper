"""标注仓储"""

import json
from typing import Dict, List, Optional

from .base import BaseRepository


class AnnotationRepository(BaseRepository):
    """标注数据仓储"""

    def __init__(self):
        super().__init__("annotations")

    def get_by_url(self, project_url: str) -> Optional[Dict]:
        """根据项目 URL 获取标注"""
        row = self.conn.execute(
            "SELECT * FROM annotations WHERE project_url = ?", (project_url,)
        ).fetchone()
        return dict(row) if row else None

    def upsert(
        self, project_url: str, note: str, priority: str = "normal", tags: List[str] = None
    ) -> bool:
        """创建或更新标注"""
        try:
            self.conn.execute(
                """INSERT OR REPLACE INTO annotations
                   (project_url, note, priority, tags, updated_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (project_url, note, priority, json.dumps(tags or [], ensure_ascii=False)),
            )
            self.conn.commit()
            return True
        except Exception as e:
            self.db.logger.error(f"Upsert annotation error: {e}")
            return False

    def delete_by_url(self, project_url: str) -> bool:
        """根据 URL 删除标注"""
        return self.delete("project_url", project_url)
