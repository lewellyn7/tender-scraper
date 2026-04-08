"""bidder_qualifications 表操作"""

import json
from typing import List, Optional

from loguru import logger


class QualificationsMixin:
    """bidder_qualifications 表 CRUD 操作（混入 Database 类使用）"""

    def add_qualification(self, data: dict) -> Optional[int]:
        """添加资质记录，返回新记录ID"""
        try:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO bidder_qualifications
                   (name, category, level, certificate_no, valid_from, valid_to,
                    issuer, file_path, linked_tenders, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data.get("name", ""),
                    data.get("category", ""),
                    data.get("level", ""),
                    data.get("certificate_no", ""),
                    data.get("valid_from") or None,
                    data.get("valid_to") or None,
                    data.get("issuer", ""),
                    data.get("file_path", ""),
                    json.dumps(data.get("linked_tenders", []), ensure_ascii=False),
                    data.get("status", "有效"),
                ),
            )
            conn.commit()
            row = conn.execute("SELECT last_insert_rowid() as id").fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.error(f"add_qualification: {e}")
            return None

    def get_qualification(self, qid: int) -> Optional[dict]:
        """获取单条资质"""
        try:
            c = self._get_conn()
            row = c.execute(
                "SELECT * FROM bidder_qualifications WHERE id = ?", (qid,)
            ).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_qualification: {e}")
            return None

    def get_qualifications(
        self,
        category: str = None,
        status: str = None,
        search: str = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple:
        """获取资质列表，支持过滤和分页，返回 (列表, 总数)"""
        try:
            c = self._get_conn()
            where = ["1=1"]
            params = []
            if category:
                where.append("category = ?")
                params.append(category)
            if status:
                where.append("status = ?")
                params.append(status)
            if search:
                where.append("(name LIKE ? OR certificate_no LIKE ?)")
                params.append(f"%{search}%")
                params.append(f"%{search}%")

            where_sql = " AND ".join(where)
            total = c.execute(
                f"SELECT COUNT(*) FROM bidder_qualifications WHERE {where_sql}", params
            ).fetchone()[0]

            offset = (page - 1) * page_size
            rows = c.execute(
                f"""SELECT * FROM bidder_qualifications
                   WHERE {where_sql}
                   ORDER BY updated_at DESC
                   LIMIT ? OFFSET ?""",
                params + [page_size, offset],
            ).fetchall()
            return [dict(r) for r in rows], total
        except Exception as e:
            logger.error(f"get_qualifications: {e}")
            return [], 0

    def update_qualification(self, qid: int, data: dict) -> bool:
        """更新资质"""
        try:
            conn = self._get_conn()
            allowed = [
                "name", "category", "level", "certificate_no",
                "valid_from", "valid_to", "issuer", "file_path",
                "linked_tenders", "status",
            ]
            updates = {k: v for k, v in data.items() if k in allowed}
            if "linked_tenders" in updates:
                updates["linked_tenders"] = json.dumps(updates["linked_tenders"], ensure_ascii=False)
            if not updates:
                return False
            set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
            values = list(updates.values()) + [qid]
            conn.execute(
                f"UPDATE bidder_qualifications SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id = ?",
                values,
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"update_qualification: {e}")
            return False

    def delete_qualification(self, qid: int) -> bool:
        """删除资质"""
        try:
            conn = self._get_conn()
            conn.execute("DELETE FROM bidder_qualifications WHERE id = ?", (qid,))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"delete_qualification: {e}")
            return False

    def get_qualifications_expiring(self, days: int = 30) -> List[dict]:
        """获取即将过期的资质"""
        try:
            c = self._get_conn()
            rows = c.execute(
                """SELECT * FROM bidder_qualifications
                   WHERE valid_to IS NOT NULL
                     AND valid_to <= date('now', ? || ' days')
                     AND valid_to >= date('now')
                     AND status = '有效'
                   ORDER BY valid_to ASC""",
                (str(days),),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_qualifications_expiring: {e}")
            return []

    def get_tender_requirements(self, tender_id: int) -> Optional[dict]:
        """获取招标项目的资质要求"""
        try:
            c = self._get_conn()
            row = c.execute(
                "SELECT * FROM favorites WHERE id = ?", (tender_id,)
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            requirements_text = d.get("bidder_requirements", "") or d.get("tender_type", "")
            return {
                "tender_id": tender_id,
                "title": d.get("title", ""),
                "requirements_text": requirements_text,
                "budget": d.get("budget", ""),
                "region": d.get("region", ""),
            }
        except Exception as e:
            logger.error(f"get_tender_requirements: {e}")
            return None

    def link_tender_to_qualification(self, qid: int, tender_id: int) -> bool:
        """将招标项目关联到资质"""
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT linked_tenders FROM bidder_qualifications WHERE id = ?", (qid,)
            ).fetchone()
            if not row:
                return False
            linked = json.loads(row[0] or "[]")
            tender_str = str(tender_id)
            if tender_str not in linked:
                linked.append(tender_str)
            conn.execute(
                "UPDATE bidder_qualifications SET linked_tenders=?, updated_at=CURRENT_TIMESTAMP WHERE id = ?",
                (json.dumps(linked, ensure_ascii=False), qid),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"link_tender_to_qualification: {e}")
            return False
