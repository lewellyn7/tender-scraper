"""annotations 表操作"""

import json
import queue
from typing import List, Optional

from loguru import logger


class AnnotationsMixin:
    """annotations 表 CRUD 操作（混入 Database 类使用）"""

    def add_annotation(
        self, project_url: str, note: str = "", priority: str = "normal", tags: list = None
    ) -> bool:
        """同步写入 annotations（直接执行，不走队列）"""
        try:
            conn = self._get_conn()
            # 2026-06-11 修复: SQLite 语法 INSERT OR REPLACE → PostgreSQL ON CONFLICT
            # 原: DB 写入失败 + syntax error at or near "OR"
            # 需先确保 PG 表 project_url 有 UNIQUE 约束 (参见 init_pg.sql:71 配套修改)
            conn.execute(
                """INSERT INTO annotations
                (project_url, note, priority, tags, updated_at)
                VALUES (?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT (project_url) DO UPDATE SET
                note=EXCLUDED.note, priority=EXCLUDED.priority,
                tags=EXCLUDED.tags, updated_at=CURRENT_TIMESTAMP""",
                (project_url, note, priority, json.dumps(tags or [], ensure_ascii=False)),
            )
            conn.commit()
            return True
        except Exception as e:
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
