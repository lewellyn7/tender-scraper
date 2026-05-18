"""关键词数据库表操作 - KeywordsMixin"""

from loguru import logger


class KeywordsMixin:
    """keywords 表 CRUD 操作（混入 Database 类使用）"""

    def _init_keywords_table(self):
        """初始化关键词表"""
        from app.database.db import USE_PG  # local import to avoid circular
        c = self._get_conn()
        if USE_PG:
            c.execute("""
                CREATE TABLE IF NOT EXISTS keywords (
                    id SERIAL PRIMARY KEY,
                    keyword VARCHAR(500) NOT NULL,
                    category VARCHAR(100) DEFAULT 'include',
                    match_mode VARCHAR(50) DEFAULT 'exact',
                    threshold REAL DEFAULT 0.8,
                    enabled INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Add unique constraint if not exists (table may already exist without it)
            c.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = 'keywords_keyword_unique'
                    ) THEN
                        ALTER TABLE keywords ADD CONSTRAINT keywords_keyword_unique UNIQUE (keyword);
                    END IF;
                END $$
            """)
        else:
            c.execute("""
                CREATE TABLE IF NOT EXISTS keywords (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT NOT NULL UNIQUE,
                    category TEXT DEFAULT 'include',
                    match_mode TEXT DEFAULT 'exact',
                    threshold REAL DEFAULT 0.8,
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_keywords_category ON keywords(category)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_keywords_enabled ON keywords(enabled)")

    def get_all_keywords(self):
        """获取所有关键词"""
        c = self._get_conn()
        rows = c.execute(
            "SELECT id, keyword, category, match_mode, threshold, enabled, created_at, updated_at FROM keywords ORDER BY category, keyword"
        ).fetchall()
        return [dict(row) for row in rows]

    def get_keywords_by_category(self, category: str):
        """按类别获取关键词"""
        c = self._get_conn()
        rows = c.execute(
            "SELECT * FROM keywords WHERE category = ? ORDER BY keyword",
            (category,)
        ).fetchall()
        return [dict(row) for row in rows]

    def add_keyword(self, keyword: str, category: str = "include",
                    match_mode: str = "exact", threshold: float = 0.8) -> bool:
        """添加关键词"""
        try:
            from app.database.db import USE_PG  # local import to avoid circular import
            c = self._get_conn()
            # PostgreSQL: use ON CONFLICT DO NOTHING (no SQLite OR IGNORE)
            if USE_PG:
                c.execute(
                    "INSERT INTO keywords (keyword, category, match_mode, threshold, enabled) "
                    "VALUES (%s, %s, %s, %s, 1) ON CONFLICT (keyword) DO NOTHING",
                    (keyword, category, match_mode, threshold)
                )
            else:
                c.execute(
                    "INSERT OR IGNORE INTO keywords (keyword, category, match_mode, threshold, enabled) VALUES (?, ?, ?, ?, 1)",
                    (keyword, category, match_mode, threshold)
                )
            return True
        except Exception as e:
            logger.warning(f"[Keywords] 添加失败: {e}")
            return False

    def update_keyword(self, keyword_id: int, **kwargs) -> bool:
        """更新关键词"""
        allowed = ['keyword', 'category', 'match_mode', 'threshold', 'enabled']
        sets = []
        vals = []
        for k, v in kwargs.items():
            if k in allowed:
                sets.append(f"{k} = ?")
                vals.append(v)
        if not sets:
            return False
        sets.append("updated_at = CURRENT_TIMESTAMP")
        vals.append(keyword_id)
        try:
            c = self._get_conn()
            c.execute(
                f"UPDATE keywords SET {', '.join(sets)} WHERE id = ?",
                tuple(vals)
            )
            return True
        except Exception as e:
            logger.warning(f"[Keywords] 更新失败: {e}")
            return False

    def delete_keyword(self, keyword_id: int) -> bool:
        """删除关键词"""
        try:
            c = self._get_conn()
            c.execute("DELETE FROM keywords WHERE id = ?", (keyword_id,))
            return True
        except Exception as e:
            logger.warning(f"[Keywords] 删除失败: {e}")
            return False

    def toggle_keyword(self, keyword_id: int) -> bool:
        """切换关键词启用状态"""
        try:
            c = self._get_conn()
            c.execute(
                "UPDATE keywords SET enabled = 1 - enabled, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (keyword_id,)
            )
            return True
        except Exception as e:
            logger.warning(f"[Keywords] 切换失败: {e}")
            return False

    def get_active_keywords(self, category: str = None):
        """获取启用的关键词"""
        c = self._get_conn()
        if category:
            rows = c.execute(
                "SELECT keyword, match_mode, threshold FROM keywords WHERE enabled = 1 AND category = ?",
                (category,)
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT keyword, category, match_mode, threshold FROM keywords WHERE enabled = 1"
            ).fetchall()

        result = {}
        for row in rows:
            cat = row['category'] if 'category' in row.keys() else 'include'
            if cat not in result:
                result[cat] = []
            result[cat].append({
                'keyword': row['keyword'],
                'match_mode': row['match_mode'] if 'match_mode' in row.keys() else 'exact',
                'threshold': row['threshold'] if 'threshold' in row.keys() else 0.8
            })
        return result

    def keywords_count(self) -> dict:
        """获取关键词统计"""
        c = self._get_conn()
        total = c.execute("SELECT COUNT(*) FROM keywords").fetchone()[0]
        enabled = c.execute(
            "SELECT COUNT(*) FROM keywords WHERE enabled = 1"
        ).fetchone()[0]
        rows = c.execute("""
            SELECT 
                category,
                COUNT(*) as total,
                SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END) as enabled
            FROM keywords
            GROUP BY category
        """).fetchall()
        return {
            "total": total,
            "enabled": enabled,
            "by_category": [dict(row) for row in rows]
        }
