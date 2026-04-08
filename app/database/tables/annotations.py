"""annotations 表操作"""

import json
import queue
from typing import List, Optional

from loguru import logger


class AnnotationsMixin:
    """annotations 表 CRUD 操作（混入 Database 类使用）"""

    def add_annotation(
        self, project_url: str, note: str, priority: str = "normal", tags: list = None
    ) -> bool:
        try:
            self._batch_queue.put(
                (
                    """INSERT OR REPLACE INTO annotations
                   (project_url, note, priority, tags, updated_at)
                   VALUES (?,?,?,?,CURRENT_TIMESTAMP)""",
                    (project_url, note, priority, json.dumps(tags or [], ensure_ascii=False)),
                )
            )
            return True
        except (queue.Full, OSError, IOError) as e:
            logger.error(f"add_annotation: {e}")
            return False

    def get_annotation(self, project_url: str) -> Optional[dict]:
        try:
            c = self._get_conn()
            row = c.execute(
                "SELECT * FROM annotations WHERE project_url=?", (project_url,)
            ).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_annotation: {e}")
            return None

    def get_all_annotations(self, limit: int = 500) -> List[dict]:
        try:
            c = self._get_conn()
            rows = c.execute(
                "SELECT * FROM annotations ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_all_annotations: {e}")
            return []

    def annotations_count(self) -> int:
        try:
            c = self._get_conn()
            return c.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
        except Exception as e:
            logger.error(f"annotations_count: {e}")
            return 0
