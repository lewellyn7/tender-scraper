"""favorites 表操作"""

import queue
from typing import List, Optional

from loguru import logger


class FavoritesMixin:
    """favorites 表 CRUD 操作（混入 Database 类使用）

    表结构：
        id, user_id, project_url (UNIQUE user+url), title, source_url,
        tender_type, budget, publish_date, status, created_at, updated_at
    """

    # ─── write paths ────────────────────────────────────────────────

    def add_favorite(self, project: dict, user_id: str = None) -> bool:
        """异步批量写入（经队列）"""
        try:
            self._batch_queue.put(
                (
                    """INSERT OR REPLACE INTO favorites
                       (user_id, project_url, title, source_url, tender_type, budget, publish_date, content_preview, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    (
                        user_id or "",
                        project.get("url", ""),
                        project.get("title", ""),
                        project.get("source_url", ""),
                        project.get("tender_type", ""),
                        project.get("budget", ""),
                        project.get("content_preview", ""),
                        project.get("publish_date", ""),
                    ),
                )
            )
            return True
        except (queue.Full, OSError, IOError) as e:
            logger.error(f"add_favorite: {e}")
            return False

    def add_favorite_sync(self, project: dict, user_id: str = None) -> bool:
        """同步添加/更新收藏（ON CONFLICT 触发 replace）"""
        uid = user_id or ""
        url = project.get("url", "")
        if not url:
            return False
        try:
            with self._get_conn() as conn:
                conn.execute(
                    """INSERT INTO favorites
                       (user_id, project_url, title, source_url, tender_type, budget, publish_date, content_preview, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                       ON CONFLICT(user_id, project_url) DO UPDATE SET
                       title=EXCLUDED.title, source_url=EXCLUDED.source_url,
                       tender_type=EXCLUDED.tender_type, budget=EXCLUDED.budget,
                       publish_date=EXCLUDED.publish_date,
                       content_preview=EXCLUDED.content_preview, updated_at=CURRENT_TIMESTAMP""",
                    (uid, url, project.get("title", ""), project.get("source_url", ""),
                     project.get("tender_type", ""), project.get("budget", ""),
                     project.get("publish_date", ""), project.get("content_preview", "")),
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"add_favorite_sync: {e}")
            return False

    def remove_favorite(self, project_url: str, user_id: str = None) -> bool:
        """删除指定用户的收藏（经队列）"""
        uid = user_id or ""
        try:
            self._batch_queue.put(
                ("DELETE FROM favorites WHERE project_url=? AND user_id=?", (project_url, uid))
            )
            return True
        except (queue.Full, OSError) as e:
            logger.error(f"remove_favorite: {e}")
            return False

    def remove_favorite_sync(self, project_url: str, user_id: str = None) -> bool:
        """同步删除指定用户的收藏（直接执行 DELETE）"""
        uid = user_id or ""
        url = project_url
        if not url:
            logger.warning("remove_favorite_sync: empty url")
            return False
        logger.info(f"remove_favorite_sync: DELETE FROM favorites WHERE project_url={repr(url)} AND user_id={repr(uid)}")
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "DELETE FROM favorites WHERE project_url=? AND user_id=?",
                    (url, uid)
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"remove_favorite_sync: {e}")
            return False

    def remove_favorite_by_id(self, fav_id: int, user_id: str = None) -> bool:
        """按 ID 同步删除收藏"""
        uid = user_id or ""
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "DELETE FROM favorites WHERE id=? AND user_id=?",
                    (fav_id, uid)
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"remove_favorite_by_id: {e}")
            return False

    def update_favorite_status(self, project_url: str, status: str, user_id: str = None) -> bool:
        """更新收藏状态"""
        uid = user_id or ""
        try:
            self._batch_queue.put(
                (
                    "UPDATE favorites SET status=?, updated_at=CURRENT_TIMESTAMP WHERE project_url=? AND user_id=?",
                    (status, project_url, uid),
                )
            )
            return True
        except (queue.Full, OSError) as e:
            logger.error(f"update_favorite_status: {e}")
            return False

    def add_favorites_batch(self, projects: List[dict], user_id: str = None) -> int:
        """批量添加收藏（事务）"""
        if not projects:
            return 0
        uid = user_id or ""
        conn = self._get_conn()
        try:
            conn.execute("BEGIN")
            count = 0
            for p in projects:
                url = p.get("url", "")
                if not url:
                    continue
                conn.execute(
                    """INSERT INTO favorites
                               (user_id, project_url, title, source_url, tender_type, budget, publish_date, updated_at)
                               VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                               ON CONFLICT(user_id, project_url) DO UPDATE SET
                               title=EXCLUDED.title, source_url=EXCLUDED.source_url,
                               tender_type=EXCLUDED.tender_type, budget=EXCLUDED.budget,
                               publish_date=EXCLUDED.publish_date,
                               content_preview=EXCLUDED.content_preview, updated_at=CURRENT_TIMESTAMP""",
                    (uid, url, p.get("title", ""), p.get("source_url", ""),
                     p.get("tender_type", ""), p.get("budget", ""), p.get("publish_date", ""), p.get("content_preview", "")),
                )
                count += 1
            conn.commit()
            return count
        except Exception as e:
            conn.rollback()
            logger.error(f"add_favorites_batch: {e}")
            return 0

    # ─── read paths ─────────────────────────────────────────────────

    def is_favorite(self, project_url: str, user_id: str = None) -> bool:
        """检查是否已收藏"""
        uid = user_id or ""
        try:
            c = self._get_conn()
            row = c.execute(
                "SELECT 1 FROM favorites WHERE project_url=? AND user_id=?",
                (project_url, uid)
            ).fetchone()
            return row is not None
        except Exception as e:
            logger.error(f"is_favorite: {e}")
            return False

    def get_favorites(
        self,
        user_id: str = None,
        status: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> List[dict]:
        """获取收藏列表（支持用户/状态过滤 + 分页）"""
        uid = user_id or ""
        try:
            c = self._get_conn()
            where, params = self._build_favorites_where(uid, status)
            rows = c.execute(
                f"""SELECT * FROM favorites
                    {where}
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?""",
                (*params, limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_favorites: {e}")
            return []

    def get_favorite_count(self, user_id: str = None, status: Optional[str] = None) -> int:
        """获取收藏总数"""
        uid = user_id or ""
        try:
            c = self._get_conn()
            where, params = self._build_favorites_where(uid, status)
            row = c.execute(
                f"SELECT COUNT(*) FROM favorites {where}", params
            ).fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error(f"get_favorite_count: {e}")
            return 0

    def get_favorite(self, project_url: str, user_id: str = None) -> Optional[dict]:
        """获取单条收藏"""
        uid = user_id or ""
        try:
            c = self._get_conn()
            row = c.execute(
                "SELECT * FROM favorites WHERE project_url=? AND user_id=?",
                (project_url, uid)
            ).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_favorite: {e}")
            return None

    def search_favorites(
        self,
        query: str,
        user_id: str = None,
        tender_type: Optional[str] = None,
        limit: int = 20,
    ) -> List[dict]:
        """全文检索收藏"""
        uid = user_id or ""
        try:
            c = self._get_conn()
            like = f"%{query}%"
            params = [uid, like, like, like]
            sql = """SELECT * FROM favorites
                     WHERE user_id=?
                       AND (title LIKE ? OR tender_type LIKE ? OR budget LIKE ?)"""
            if tender_type:
                sql += " AND tender_type = ?"
                params.append(tender_type)
            sql += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)
            rows = c.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"search_favorites: {e}")
            return []

    # ─── internal ──────────────────────────────────────────────────

    def _build_favorites_where(self, user_id: str, status: Optional[str]):
        """构建 WHERE 子句和参数列表"""
        conditions = ["user_id=?"]
        params = [user_id]
        if status:
            conditions.append("status=?")
            params.append(status)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        return where, params
