"""SQLite 数据库 - 优化版"""

import json
import os
import queue
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from loguru import logger

from app.constants import BatchConstants  # noqa: E402

DB_PATH = Path(__file__).parent.parent.parent / "config" / "tender_scraper.db"


class Database:
    _local = threading.local()
    _instance = None
    _lock = threading.Lock()
    _batch_queue = queue.Queue()
    _batch_size = BatchConstants.DEFAULT_BATCH_SIZE
    _shutdown = False
    _batch_thread = None

    def __new__(cls, db_path=None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path=None):
        if self._initialized:
            return
        self.db_path = db_path or str(DB_PATH)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._batch_queue = queue.Queue()
        self._batch_size = BatchConstants.DEFAULT_BATCH_SIZE
        self._shutdown = False
        self._batch_thread = threading.Thread(target=self._batch_writer, daemon=True)
        self._batch_thread.start()
        self._init_tables()
        self._initialized = True
        logger.info(f"DB (singleton): {self.db_path}")

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn.execute("PRAGMA cache_size=-64000")
            self._local.conn.execute("PRAGMA temp_store=MEMORY")
        return self._local.conn

    def _init_tables(self):
        c = self._get_conn()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS favorites(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_url TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                source_url TEXT DEFAULT "",
                tender_type TEXT DEFAULT "",
                budget TEXT DEFAULT "",
                publish_date TEXT DEFAULT "",
                status TEXT DEFAULT "pending",
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS annotations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_url TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT "",
                priority TEXT DEFAULT "normal",
                tags TEXT DEFAULT "[]",
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS filter_presets(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                preset_key TEXT UNIQUE NOT NULL,
                filter_config TEXT NOT NULL,
                is_default INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS config_backups(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_label TEXT NOT NULL,
                config_data TEXT NOT NULL,
                description TEXT DEFAULT "",
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS scrape_logs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                log_level TEXT NOT NULL,
                message TEXT NOT NULL,
                source TEXT DEFAULT "system",
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS duplicate_records(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_url TEXT NOT NULL,
                duplicate_url TEXT NOT NULL,
                duplicate_title TEXT DEFAULT "",
                similarity_score REAL DEFAULT 0,
                detected_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS data_cache(
                cache_key TEXT PRIMARY KEY,
                cache_value TEXT NOT NULL,
                expires_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS users(
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                display_name TEXT DEFAULT "",
                role TEXT DEFAULT "viewer",
                enabled INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_login TEXT
            );
        """)
        c.commit()
        self._init_indexes()

    def _init_indexes(self):
        c = self._get_conn()
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_favorites_url ON favorites(project_url);",
            "CREATE INDEX IF NOT EXISTS idx_favorites_status ON favorites(status);",
            "CREATE INDEX IF NOT EXISTS idx_favorites_updated ON favorites(updated_at);",
            "CREATE INDEX IF NOT EXISTS idx_annotations_url ON annotations(project_url);",
            "CREATE INDEX IF NOT EXISTS idx_logs_level ON scrape_logs(log_level);",
            "CREATE INDEX IF NOT EXISTS idx_logs_created ON scrape_logs(created_at);",
            "CREATE INDEX IF NOT EXISTS idx_duplicates_canonical ON duplicate_records(canonical_url);",
            "CREATE INDEX IF NOT EXISTS idx_cache_key ON data_cache(cache_key);",
            "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);",
            "CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);",
        ]
        for idx in indexes:
            c.execute(idx)
        c.commit()

    def _batch_writer(self):
        batch = []
        while not self._shutdown:
            try:
                item = self._batch_queue.get(timeout=1)
                batch.append(item)
                while len(batch) < self._batch_size and not self._batch_queue.empty():
                    try:
                        batch.append(self._batch_queue.get_nowait())
                    except queue.Empty:
                        break
                if batch:
                    self._execute_batch(batch)
                    batch.clear()
            except queue.Empty:
                if batch:
                    self._execute_batch(batch)
                    batch.clear()
            except (OSError, IOError) as e:
                logger.error(f"_batch_writer: {e}")
        while not self._batch_queue.empty():
            try:
                batch.append(self._batch_queue.get_nowait())
            except queue.Empty:
                break
        if batch:
            self._execute_batch(batch)

    def _execute_batch(self, batch: list):
        if not batch:
            return
        conn = self._get_conn()
        try:
            conn.execute("BEGIN")
            for sql, params in batch:
                conn.execute(sql, params)
            conn.execute("COMMIT")
        except (sqlite3.IntegrityError, sqlite3.OperationalError, OSError) as e:
            conn.execute("ROLLBACK")
            logger.error(f"_execute_batch: {e}")

    # ==================== favorites ====================

    def add_favorite(self, project: dict) -> bool:
        try:
            self._batch_queue.put(
                (
                    """INSERT OR REPLACE INTO favorites
                   (project_url, title, source_url, tender_type, budget, publish_date, updated_at)
                   VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    (
                        project.get("url", ""),
                        project.get("title", ""),
                        project.get("source_url", ""),
                        project.get("tender_type", ""),
                        project.get("budget", ""),
                        project.get("publish_date", ""),
                    ),
                )
            )
            return True
        except (queue.Full, OSError, IOError) as e:
            logger.error(f"add_favorite: {e}")
            return False

    def add_favorite_sync(self, project: dict) -> bool:
        try:
            with self._get_conn() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO favorites
                   (project_url, title, source_url, tender_type, budget, publish_date, updated_at)
                   VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    (
                        project.get("url", ""),
                        project.get("title", ""),
                        project.get("source_url", ""),
                        project.get("tender_type", ""),
                        project.get("budget", ""),
                        project.get("publish_date", ""),
                    ),
                )
                conn.commit()
            return True
        except (sqlite3.IntegrityError, sqlite3.OperationalError, OSError) as e:
            logger.error(f"add_favorite_sync: {e}")
            return False

    def remove_favorite(self, project_url: str) -> bool:
        try:
            self._batch_queue.put(("DELETE FROM favorites WHERE project_url=?", (project_url,)))
            return True
        except (queue.Full, OSError) as e:
            logger.error(f"remove_favorite: {e}")
            return False

    def is_favorite(self, project_url: str) -> bool:
        try:
            c = self._get_conn()
            result = c.execute(
                "SELECT 1 FROM favorites WHERE project_url=?", (project_url,)
            ).fetchone()
            return result is not None
        except (sqlite3.OperationalError, OSError) as e:
            logger.error(f"is_favorite: {e}")
            return False

    def get_favorites(self, status: str = None, limit: int = 500) -> List[dict]:
        try:
            c = self._get_conn()
            if status:
                rows = c.execute(
                    """SELECT * FROM favorites WHERE status=?
                                   ORDER BY updated_at DESC LIMIT ?""",
                    (status, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM favorites ORDER BY updated_at DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
        except (sqlite3.OperationalError, OSError) as e:
            logger.error(f"get_favorites: {e}")
            return []

    def update_favorite_status(self, project_url: str, status: str) -> bool:
        try:
            self._batch_queue.put(
                (
                    "UPDATE favorites SET status=?, updated_at=CURRENT_TIMESTAMP WHERE project_url=?",
                    (status, project_url),
                )
            )
            return True
        except (queue.Full, OSError) as e:
            logger.error(f"update_favorite_status: {e}")
            return False

    def add_favorites_batch(self, projects: List[dict]) -> int:
        if not projects:
            return 0
        count = 0
        conn = self._get_conn()
        try:
            conn.execute("BEGIN")
            for p in projects:
                conn.execute(
                    """INSERT OR IGNORE INTO favorites
                               (project_url, title, source_url, tender_type, budget, publish_date, updated_at)
                               VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    (
                        p.get("url", ""),
                        p.get("title", ""),
                        p.get("source_url", ""),
                        p.get("tender_type", ""),
                        p.get("budget", ""),
                        p.get("publish_date", ""),
                    ),
                )
                count += 1
            conn.execute("COMMIT")
        except (sqlite3.IntegrityError, sqlite3.OperationalError, OSError) as e:
            conn.execute("ROLLBACK")
            logger.error(f"add_favorites_batch: {e}")
            return 0
        return count

    # ==================== annotations ====================

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
        except (sqlite3.OperationalError, OSError) as e:
            logger.error(f"get_annotation: {e}")
            return None

    def get_all_annotations(self, limit: int = 500) -> List[dict]:
        try:
            c = self._get_conn()
            rows = c.execute(
                "SELECT * FROM annotations ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        except (sqlite3.OperationalError, OSError) as e:
            logger.error(f"get_all_annotations: {e}")
            return []

    def annotations_count(self) -> int:
        try:
            c = self._get_conn()
            return c.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
        except (sqlite3.OperationalError, OSError) as e:
            logger.error(f"annotations_count: {e}")
            return 0

    # ==================== presets ====================

    def save_preset(
        self, name: str, preset_key: str, filter_config: dict, is_default: bool = False
    ) -> bool:
        try:
            conn = self._get_conn()
            if is_default:
                conn.execute("UPDATE filter_presets SET is_default=0")
            conn.execute(
                """INSERT OR REPLACE INTO filter_presets
                           (name, preset_key, filter_config, is_default)
                           VALUES (?,?,?,?)""",
                (
                    name,
                    preset_key,
                    json.dumps(filter_config, ensure_ascii=False),
                    1 if is_default else 0,
                ),
            )
            conn.commit()
            return True
        except (sqlite3.IntegrityError, sqlite3.OperationalError, OSError) as e:
            logger.error(f"save_preset: {e}")
            return False

    def get_presets(self) -> List[dict]:
        try:
            c = self._get_conn()
            rows = c.execute(
                "SELECT * FROM filter_presets ORDER BY is_default DESC, created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        except (sqlite3.OperationalError, OSError) as e:
            logger.error(f"get_presets: {e}")
            return []

    def get_preset(self, preset_key: str) -> Optional[dict]:
        try:
            c = self._get_conn()
            row = c.execute(
                "SELECT * FROM filter_presets WHERE preset_key=?", (preset_key,)
            ).fetchone()
            return dict(row) if row else None
        except (sqlite3.OperationalError, OSError) as e:
            logger.error(f"get_preset: {e}")
            return None

    def delete_preset(self, preset_key: str) -> bool:
        try:
            self._batch_queue.put(("DELETE FROM filter_presets WHERE preset_key=?", (preset_key,)))
            return True
        except (queue.Full, OSError) as e:
            logger.error(f"delete_preset: {e}")
            return False

    # ==================== logs ====================

    def add_log(self, level: str, message: str, source: str = "system") -> bool:
        try:
            self._batch_queue.put(
                (
                    "INSERT INTO scrape_logs(log_level, message, source) VALUES (?,?,?)",
                    (level, message, source),
                )
            )
            return True
        except (queue.Full, OSError, IOError) as e:
            logger.error(f"add_log: {e}")
            return False

    def get_logs(self, level: str = None, limit: int = 200) -> List[dict]:
        try:
            c = self._get_conn()
            if level:
                rows = c.execute(
                    """SELECT * FROM scrape_logs WHERE log_level=?
                                   ORDER BY created_at DESC LIMIT ?""",
                    (level, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM scrape_logs ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
        except (sqlite3.OperationalError, OSError) as e:
            logger.error(f"get_logs: {e}")
            return []

    def clear_logs(self, before_days: int = 7) -> bool:
        try:
            self._batch_queue.put(
                (
                    f"DELETE FROM scrape_logs WHERE created_at < datetime('now', '-{before_days} days')",
                    (),
                )
            )
            return True
        except (queue.Full, OSError) as e:
            logger.error(f"clear_logs: {e}")
            return False

    # ==================== duplicates ====================

    def add_duplicate(
        self, canonical_url: str, duplicate_url: str, title: str = "", similarity: float = 0
    ) -> bool:
        try:
            self._batch_queue.put(
                (
                    """INSERT OR IGNORE INTO duplicate_records
                   (canonical_url, duplicate_url, duplicate_title, similarity_score) VALUES (?,?,?,?)""",
                    (canonical_url, duplicate_url, title, similarity),
                )
            )
            return True
        except (queue.Full, OSError, IOError) as e:
            logger.error(f"add_duplicate: {e}")
            return False

    def get_duplicates(self, canonical_url: str = None, limit: int = 200) -> List[dict]:
        try:
            c = self._get_conn()
            if canonical_url:
                rows = c.execute(
                    """SELECT * FROM duplicate_records WHERE canonical_url=?
                                   ORDER BY similarity_score DESC LIMIT ?""",
                    (canonical_url, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM duplicate_records ORDER BY similarity_score DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        except (sqlite3.OperationalError, OSError) as e:
            logger.error(f"get_duplicates: {e}")
            return []

    # ==================== cache ====================

    def get_cached(self, key: str) -> Optional[dict]:
        try:
            c = self._get_conn()
            row = c.execute(
                """SELECT cache_value FROM data_cache
                              WHERE cache_key=? AND (expires_at IS NULL OR expires_at > datetime('now'))""",
                (key,),
            ).fetchone()
            return json.loads(row[0]) if row else None
        except (sqlite3.OperationalError, OSError) as e:
            logger.error(f"get_cached: {e}")
            return None

    def set_cached(self, key: str, value: dict, ttl_seconds: int = 3600) -> bool:
        try:
            self._batch_queue.put(
                (
                    """INSERT OR REPLACE INTO data_cache (cache_key, cache_value, expires_at)
                   VALUES (?,?,datetime('now', '+' || ? || ' seconds'))""",
                    (key, json.dumps(value, ensure_ascii=False), ttl_seconds),
                )
            )
            return True
        except (queue.Full, OSError, IOError) as e:
            logger.error(f"set_cached: {e}")
            return False

    def invalidate_cache(self, pattern: str = None) -> bool:
        import re

        try:
            conn = self._get_conn()
            if pattern:
                # 验证 pattern 只包含合法字符（防止 LIKE 注入）
                if not re.match(r"^[\w*-]+$", pattern):
                    logger.warning(f"Invalid cache pattern: {pattern}")
                    return False
                safe_pattern = pattern.replace("*", "%")
                conn.execute("DELETE FROM data_cache WHERE cache_key LIKE ?", (safe_pattern,))
            else:
                conn.execute("DELETE FROM data_cache")
            conn.commit()
            return True
        except (sqlite3.OperationalError, OSError) as e:
            logger.error(f"invalidate_cache: {e}")
            return False

    # ==================== users ====================

    def create_user(self, user_data: dict) -> str:
        try:
            c = self._get_conn()
            c.execute(
                """
                INSERT INTO users (user_id, username, password_hash, password_salt, display_name, role, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    user_data.get("user_id", f"user_{int(time.time() * 1000)}"),
                    user_data.get("username"),
                    user_data.get("password_hash"),
                    user_data.get("password_salt"),
                    user_data.get("display_name", user_data.get("username")),
                    user_data.get("role", "viewer"),
                    1 if user_data.get("enabled", True) else 0,
                    user_data.get("created_at", datetime.now().isoformat()),
                ),
            )
            c.commit()
            return user_data.get("user_id", f"user_{int(time.time() * 1000)}")
        except (sqlite3.IntegrityError, sqlite3.OperationalError, OSError) as e:
            logger.error(f"create_user: {e}")
            return None

    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        try:
            c = self._get_conn()
            row = c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return dict(row) if row else None
        except (sqlite3.OperationalError, OSError) as e:
            logger.error(f"get_user_by_id: {e}")
            return None

    def get_user_by_username(self, username: str) -> Optional[dict]:
        try:
            c = self._get_conn()
            row = c.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            return dict(row) if row else None
        except (sqlite3.OperationalError, OSError) as e:
            logger.error(f"get_user_by_username: {e}")
            return None

    def update_user(self, user_id: str, updates: dict):
        try:
            conn = self._get_conn()
            set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
            values = list(updates.values()) + [user_id]
            conn.execute(
                f"UPDATE users SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                values,
            )
            conn.commit()
        except (sqlite3.OperationalError, sqlite3.IntegrityError, OSError) as e:
            logger.error(f"update_user: {e}")

    def update_user_password(self, user_id: str, pwd_hash: str, pwd_salt: str):
        try:
            conn = self._get_conn()
            conn.execute(
                "UPDATE users SET password_hash = ?, password_salt = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (pwd_hash, pwd_salt, user_id),
            )
            conn.commit()
        except (sqlite3.OperationalError, sqlite3.IntegrityError, OSError) as e:
            logger.error(f"update_user_password: {e}")

    def update_user_last_login(self, user_id: str):
        try:
            conn = self._get_conn()
            conn.execute(
                "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,)
            )
            conn.commit()
        except (sqlite3.OperationalError, sqlite3.IntegrityError, OSError) as e:
            logger.error(f"update_user_last_login: {e}")

    def delete_user(self, user_id: str):
        try:
            conn = self._get_conn()
            conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            conn.commit()
        except (sqlite3.OperationalError, sqlite3.IntegrityError, OSError) as e:
            logger.error(f"delete_user: {e}")

    def list_users_paged(
        self, page: int = 1, page_size: int = 20, role: str = None, enabled: bool = None
    ) -> tuple:
        try:
            c = self._get_conn()
            where = "WHERE 1=1"
            params = []
            if role:
                where += " AND role = ?"
                params.append(role)
            if enabled is not None:
                where += " AND enabled = ?"
                params.append(1 if enabled else 0)
            total = c.execute(f"SELECT COUNT(*) FROM users {where}", params).fetchone()[0]
            offset = (page - 1) * page_size
            rows = c.execute(
                f"SELECT * FROM users {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [page_size, offset],
            ).fetchall()
            return [dict(r) for r in rows], total
        except (sqlite3.OperationalError, OSError) as e:
            logger.error(f"list_users_paged: {e}")
            return [], 0

    def get_user_stats(self) -> dict:
        try:
            c = self._get_conn()
            return {
                "total": c.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                "active": c.execute("SELECT COUNT(*) FROM users WHERE enabled = 1").fetchone()[0],
                "admins": c.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[
                    0
                ],
                "operators": c.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'operator'"
                ).fetchone()[0],
            }
        except (sqlite3.OperationalError, OSError) as e:
            logger.error(f"get_user_stats: {e}")
            return {"total": 0, "active": 0, "admins": 0, "operators": 0}

    # ==================== stats ====================

    def get_stats(self) -> dict:
        try:
            c = self._get_conn()
            return {
                "favorites_count": c.execute("SELECT COUNT(*) FROM favorites").fetchone()[0],
                "annotations_count": c.execute("SELECT COUNT(*) FROM annotations").fetchone()[0],
                "presets_count": c.execute("SELECT COUNT(*) FROM filter_presets").fetchone()[0],
                "backups_count": c.execute("SELECT COUNT(*) FROM config_backups").fetchone()[0],
                "logs_count": c.execute("SELECT COUNT(*) FROM scrape_logs").fetchone()[0],
                "duplicates_count": c.execute("SELECT COUNT(*) FROM duplicate_records").fetchone()[
                    0
                ],
            }
        except (sqlite3.OperationalError, OSError) as e:
            logger.error(f"get_stats: {e}")
            return {}

    # ==================== 数据库文件备份 ====================

    def backup_database(self) -> Optional[str]:
        """备份整个数据库文件"""
        try:
            import hashlib
            import shutil
            from datetime import datetime

            backup_dir = Path(self.db_path).parent / "db_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)

            # 生成备份文件名: tender_scraper_20240101_120000.db
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_dir / f"tender_scraper_{timestamp}.db"

            # 关闭所有连接以确保备份一致性
            if hasattr(self._local, "conn") and self._local.conn:
                self._local.conn.close()
                self._local.conn = None

            # 复制数据库文件
            shutil.copy2(self.db_path, str(backup_path))

            # 同时备份 WAL 和 SHM 文件（如果存在）
            wal_path = Path(self.db_path + "-wal")
            shm_path = Path(self.db_path + "-shm")
            if wal_path.exists():
                shutil.copy2(str(wal_path), str(backup_path) + "-wal")
            if shm_path.exists():
                shutil.copy2(str(shm_path), str(backup_path) + "-shm")

            # 添加 checksum
            checksum_path = str(backup_path) + ".sha256"
            with open(backup_path, "rb") as f:
                checksum = hashlib.sha256(f.read()).hexdigest()
            with open(checksum_path, "w") as f:
                f.write(checksum)

            # 设置安全权限
            os.chmod(backup_path, 0o600)
            os.chmod(checksum_path, 0o600)

            logger.info(f"数据库备份成功: {backup_path}")
            return str(backup_path)
        except (OSError, IOError) as e:
            logger.error(f"数据库备份失败: {e}")
            return None

    def verify_backup(self, backup_path: str) -> bool:
        """验证备份完整性"""
        try:
            import hashlib

            checksum_path = backup_path + ".sha256"
            if not Path(checksum_path).exists():
                return False
            stored = open(checksum_path).read()
            current = hashlib.sha256(open(backup_path, "rb").read()).hexdigest()
            return stored == current
        except (OSError, IOError) as e:
            logger.error(f"备份校验失败: {e}")
            return False

    def list_db_backups(self, limit: int = 10) -> List[dict]:
        """列出数据库备份"""
        try:
            from datetime import datetime

            backup_dir = Path(self.db_path).parent / "db_backups"
            if not backup_dir.exists():
                return []

            backups = []
            for f in sorted(backup_dir.glob("tender_scraper_*.db"), reverse=True)[:limit]:
                stat = f.stat()
                backups.append(
                    {
                        "path": str(f),
                        "filename": f.name,
                        "size": stat.st_size,
                        "size_mb": round(stat.st_size / 1024 / 1024, 2),
                        "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    }
                )
            return backups
        except (OSError, IOError) as e:
            logger.error(f"列出数据库备份失败: {e}")
            return []

    def restore_database(self, backup_path: str) -> bool:
        """从备份恢复数据库"""
        try:
            import shutil

            backup_file = Path(backup_path)
            if not backup_file.exists():
                logger.error(f"备份文件不存在: {backup_path}")
                return False

            # 关闭所有连接
            if hasattr(self._local, "conn") and self._local.conn:
                self._local.conn.close()
                self._local.conn = None

            # 创建当前数据库的备份（以防万一）
            current_backup = (
                Path(self.db_path).parent
                / "db_backups"
                / f"auto_recover_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            )
            shutil.copy2(self.db_path, str(current_backup))

            # 替换数据库文件
            shutil.copy2(backup_path, self.db_path)

            # 恢复 WAL 和 SHM 文件
            if Path(backup_path + "-wal").exists():
                shutil.copy2(backup_path + "-wal", self.db_path + "-wal")
            if Path(backup_path + "-shm").exists():
                shutil.copy2(backup_path + "-shm", self.db_path + "-shm")

            logger.info(f"数据库恢复成功: {backup_path}")
            return True
        except (OSError, IOError) as e:
            logger.error(f"数据库恢复失败: {e}")
            return False

    def delete_db_backup(self, backup_path: str) -> bool:
        """删除数据库备份"""
        try:
            import os

            backup_file = Path(backup_path)
            if backup_file.exists():
                os.remove(backup_path)
                # 同时删除 WAL 和 SHM
                wal_path = backup_path + "-wal"
                shm_path = backup_path + "-shm"
                if Path(wal_path).exists():
                    os.remove(wal_path)
                if Path(shm_path).exists():
                    os.remove(shm_path)
                logger.info(f"删除备份: {backup_path}")
            return True
        except (OSError, IOError) as e:
            logger.error(f"删除备份失败: {e}")
            return False

    def cleanup_old_backups(self, keep_count: int = 10) -> int:
        """清理旧备份，保留最近的 N 个"""
        try:

            backup_dir = Path(self.db_path).parent / "db_backups"
            if not backup_dir.exists():
                return 0

            # 获取所有备份按时间排序
            backups = sorted(
                backup_dir.glob("tender_scraper_*.db"),
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )

            # 删除多余的
            deleted = 0
            for old_backup in backups[keep_count:]:
                self.delete_db_backup(str(old_backup))
                deleted += 1

            logger.info(f"清理了 {deleted} 个旧备份")
            return deleted
        except (OSError, IOError) as e:
            logger.error(f"清理旧备份失败: {e}")
            return 0

    def get_schema_version(self) -> int:
        try:
            c = self._get_conn()
            row = c.execute("SELECT version FROM schema_version").fetchone()
            return row[0] if row else 0
        except (sqlite3.OperationalError, OSError):
            return 0

    def set_schema_version(self, version: int):
        try:
            conn = self._get_conn()
            conn.execute("INSERT OR REPLACE INTO schema_version VALUES (?)", (version,))
            conn.commit()
        except (sqlite3.OperationalError, sqlite3.IntegrityError, OSError) as e:
            logger.error(f"set_schema_version: {e}")

    def close(self):
        self._shutdown = True
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


_db_instance = None
_db_lock = threading.Lock()


def get_db() -> Database:
    global _db_instance
    if _db_instance is None:
        with _db_lock:
            if _db_instance is None:
                _db_instance = Database()
    return _db_instance
