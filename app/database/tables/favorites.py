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
        """获取收藏列表（支持用户/状态过滤 + 分页，关联 annotations）"""
        uid = user_id or ""
        try:
            c = self._get_conn()
            where, params = self._build_favorites_where(uid, status)
            rows = c.execute(
                f"""SELECT f.*, a.note AS ann_note, a.priority AS ann_priority, a.tags AS ann_tags
                    FROM favorites f
                    LEFT JOIN annotations a ON a.project_url = f.project_url
                    {where}
                    ORDER BY f.updated_at DESC
                    LIMIT ? OFFSET ?""",
                (*params, limit, offset),
            ).fetchall()
            return [self._attach_annotation(dict(r)) for r in rows]
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
        """获取单条收藏（关联 annotations 表）"""
        uid = user_id or ""
        try:
            c = self._get_conn()
            row = c.execute(
                """SELECT f.*, a.note AS ann_note, a.priority AS ann_priority, a.tags AS ann_tags
                   FROM favorites f
                   LEFT JOIN annotations a ON a.project_url = f.project_url
                   WHERE f.project_url=? AND f.user_id=?""",
                (project_url, uid),
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            return self._attach_annotation(d)
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
        """全文检索收藏（关联 annotations）"""
        uid = user_id or ""
        try:
            c = self._get_conn()
            like = f"%{query}%"
            params = [uid, like, like, like]
            sql = """SELECT f.*, a.note AS ann_note, a.priority AS ann_priority, a.tags AS ann_tags
                     FROM favorites f
                     LEFT JOIN annotations a ON a.project_url = f.project_url
                     WHERE f.user_id=?
                       AND (f.title LIKE ? OR f.tender_type LIKE ? OR f.budget LIKE ?)"""
            if tender_type:
                sql += " AND f.tender_type = ?"
                params.append(tender_type)
            sql += " ORDER BY f.updated_at DESC LIMIT ?"
            params.append(limit)
            rows = c.execute(sql, params).fetchall()
            return [self._attach_annotation(dict(r)) for r in rows]
        except Exception as e:
            logger.error(f"search_favorites: {e}")
            return []

    @staticmethod
    def _attach_annotation(row: dict) -> dict:
        """把 ann_note/ann_priority/ann_tags 字段组合成 annotation dict，移除临时字段。

        2026-06-12 添加: 让 /api/favorites 列表能直接返回 annotation 字段供前端显示。
        LEFT JOIN 拿不到 annotation 行时 (ann_*) 全为 None → annotation = None。
        """
        if row is None:
            return None
        ann_note = row.pop("ann_note", None)
        ann_priority = row.pop("ann_priority", None)
        ann_tags = row.pop("ann_tags", None)
        if ann_note is None and ann_priority is None and ann_tags is None:
            row["annotation"] = None
        else:
            row["annotation"] = {
                "note": ann_note or "",
                "priority": ann_priority or "normal",
                "tags": ann_tags or [],
            }
        return row

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

    # ─── favorite match (project linking) ─────────────────────────

    def find_favorite_matches(
        self,
        record_url: str,
        project_name: str = "",
        project_no: str = "",
        info_type: str = "",
    ) -> List[dict]:
        """查找可能与新 record 关联的收藏项目。

        匹配策略（按优先级去重）：
        1. URL 完全相同 — 同一项目同一记录
        2. 规范化名称相同 — 同一项目的不同阶段（答疑补遗 vs 招标公告）
        3. 项目编号相同 — 跨站点的同一项目

        返回：List[{user_id, project_url, title, tender_type, match_type}]
        match_type: 'url' | 'name' | 'project_no'

        注意：不限制 user_id — 任何用户只要收藏了该项目就应收到提醒。
        """
        from app.utils.project_linker import normalize_project_name

        results: List[dict] = []
        seen: set = set()  # (user_id, project_url) 去重

        try:
            c = self._get_conn()
            # 取全部 favorites（最多 5000），再 Python 端去重匹配。
            # 收藏数据规模小（百量级），全表扫可接受。
            rows = c.execute(
                "SELECT user_id, project_url, title, tender_type, budget, publish_date "
                "FROM favorites LIMIT 5000"
            ).fetchall()
            fav_list = [dict(r) for r in rows] if rows else []
        except Exception as e:
            logger.error(f"find_favorite_matches: {e}")
            return []

        for fav in fav_list:
            uid = fav.get("user_id", "")
            fpu = fav.get("project_url", "")
            key = (uid, fpu)
            if key in seen:
                continue

            match_type = None

            # 策略 1: URL 完全相同
            if record_url and fpu and record_url == fpu:
                match_type = "url"
            # 策略 2: 名称匹配（双向子串含项目编号）
            elif project_name and fav.get("title"):
                p_name_norm = normalize_project_name(project_name)
                f_name_norm = normalize_project_name(fav["title"])
                if p_name_norm and f_name_norm:
                    # 完全相等 OR 互为子串（处理 fav.title 比 project_name 多 "分包5" 等细节的情况）
                    if p_name_norm == f_name_norm:
                        match_type = "name"
                    elif len(p_name_norm) >= 6 and p_name_norm in f_name_norm:
                        match_type = "name_contains"
                    elif len(f_name_norm) >= 6 and f_name_norm in p_name_norm:
                        match_type = "name_contains"
            # 策略 3: 项目编号相同（从 favorites.title 中也提取一遍）
            if not match_type and project_no:
                from app.utils.project_linker import extract_project_no
                fav_pno = extract_project_no(fav.get("title", ""), "")
                if fav_pno and project_no and fav_pno == project_no:
                    match_type = "project_no"

            if match_type:
                results.append({**fav, "match_type": match_type})
                seen.add(key)

        return results

