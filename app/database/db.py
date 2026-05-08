"""SQLite 数据库 - 优化版（PostgreSQL QueuePool + SQLite）

已拆分为表模块：
  - app.database.tables.favorites        : favorites 表
  - app.database.tables.annotations      : annotations 表
  - app.database.tables.qualifications  : bidder_qualifications 表
  - app.database.tables.users           : users 表
  - app.database.tables.modals           : filter_presets / logs / duplicates / cache / backup / stats / schema
"""

import os
import queue
import re
from contextlib import contextmanager
import threading
from pathlib import Path

from loguru import logger

from app.constants import BatchConstants
from app.database.tables import (
    AnnotationsMixin,
    FavoritesMixin,
    ModalsMixin,
    QualificationsMixin,
    UsersMixin,
    KeywordsMixin,
)

DB_PATH = Path(__file__).parent.parent.parent / "config" / "tender_scraper.db"
DATABASE_URL = os.getenv("DATABASE_URL", "")
USE_PG = DATABASE_URL.startswith("postgresql://")

# PostgreSQL connection pool
_pg_pool = None

# Allow env override since this pool serves sync FastAPI routes (analytics, health, permissions)
_PG_POOL_MIN = int(os.getenv("DB_POOL_MIN", "5"))
_PG_POOL_MAX = int(os.getenv("DB_POOL_MAX", "50"))


def _build_pg_url():
    """Build PostgreSQL URL from DATABASE_URL env var."""
    return DATABASE_URL


def _get_pg_pool():
    global _pg_pool
    if _pg_pool is None:
        import psycopg2
        from psycopg2 import pool
        _pg_pool = pool.ThreadedConnectionPool(
            minconn=_PG_POOL_MIN,
            maxconn=_PG_POOL_MAX,
            dsn=DATABASE_URL,
            connect_timeout=10,
        )
        logger.info(
            f"PG connection pool started: minconn={_PG_POOL_MIN}, maxconn={_PG_POOL_MAX}"
        )
    return _pg_pool


def _pg_conn():
    """Get a PostgreSQL connection"""
    pool = _get_pg_pool()
    conn = pool.getconn()
    conn.autocommit = False
    return conn


def _pg_close_conn(conn):
    """Return connection to pool"""
    if isinstance(conn, PGConnectionWrapper):
        conn = conn.conn
    pool = _get_pg_pool()
    try:
        conn.rollback()
    except Exception:
        pass
    pool.putconn(conn)


def _convert_placeholders(query: str) -> str:
    """Convert SQLite-style ? placeholders to PostgreSQL %s for query translation."""
    return query.replace("?", "%s")


class PGCursorWrapper:
    """Wraps psycopg2 cursor so fetchone()/fetchall() return dict-like objects.
    This makes dict(row) work the same way as sqlite3.Row."""

    __slots__ = ("cursor", "columns")

    def __init__(self, cursor):
        self.cursor = cursor
        self.columns = None

    def _ensure_columns(self):
        if self.columns is None:
            self.columns = (
                [desc[0] for desc in self.cursor.description]
                if self.cursor.description
                else []
            )

    def fetchone(self):
        self._ensure_columns()
        row = self.cursor.fetchone()
        if row is None:
            return None
        return _DictRow(row, self.columns)

    def fetchall(self):
        self._ensure_columns()
        rows = self.cursor.fetchall()
        return [_DictRow(r, self.columns) for r in rows]

    def fetchmany(self, size=None):
        self._ensure_columns()
        rows = self.cursor.fetchmany(size) if size else self.cursor.fetchmany()
        return [_DictRow(r, self.columns) for r in rows]

    def close(self):
        self.cursor.close()

    @property
    def description(self):
        return self.cursor.description

    def __iter__(self):
        return self

    def __next__(self):
        row = self.fetchone()
        if row is None:
            raise StopIteration
        return row


class _DictRow:
    """A dict-like row that also supports dict() conversion."""

    __slots__ = ("_row", "_keys")

    def __init__(self, row, columns):
        self._row = row
        self._keys = columns

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._row[key]
        return self._row[self._keys.index(key)]

    def keys(self):
        return self._keys

    def values(self):
        return self._row

    def items(self):
        return list(zip(self._keys, self._row))

    def __len__(self):
        return len(self._row)

    def __iter__(self):
        return iter(self._row)

    def __repr__(self):
        return f"<DictRow({dict(self)})>"

    def __eq__(self, other):
        if isinstance(other, _DictRow):
            return self._row == other._row and self._keys == other._keys
        if isinstance(other, dict):
            return dict(self) == other
        return False


class PGConnectionWrapper:
    """Wraps psycopg2 connection to auto-convert ? placeholders to %s."""

    __slots__ = ("conn",)

    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        """Execute SQL and return a cursor."""
        converted = _convert_placeholders(sql)
        cursor = self.conn.cursor()
        if params is None:
            cursor.execute(converted)
        else:
            cursor.execute(converted, params)
        return PGCursorWrapper(cursor)

    def executemany(self, sql, params_list):
        """Execute SQL for many params."""
        converted = _convert_placeholders(sql)
        cursor = self.conn.cursor()
        cursor.executemany(converted, params_list)
        return PGCursorWrapper(cursor)

    def cursor(self, *args, **kwargs):
        return self.conn.cursor(*args, **kwargs)

    def commit(self):
        return self.conn.commit()

    def rollback(self):
        return self.conn.rollback()

    def close(self):
        """Return connection to pool (rollback first to clean transaction)."""
        try:
            self.conn.rollback()
        except Exception:
            pass
        _pg_close_conn(self.conn)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.conn.rollback()
        return False

    @property
    def dsn(self):
        return self.conn.dsn


class Database(
    FavoritesMixin,
    AnnotationsMixin,
    QualificationsMixin,
    UsersMixin,
    ModalsMixin,
    KeywordsMixin,
):
    """PostgreSQL 数据库单例（混合了所有表操作Mixin）"""

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
        logger.info(f"DB (singleton): {self.db_path} | PG={USE_PG}")

    def _get_conn(self):
        """Always returns PostgreSQL connection."""
        if not hasattr(self._local, "pg_conn") or self._local.pg_conn is None:
            self._local.pg_conn = _pg_conn()
        return PGConnectionWrapper(self._local.pg_conn)

    @contextmanager
    def _pg_transaction(self):
        """Context manager for PostgreSQL transactions."""
        conn = self._get_conn().conn
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()

    def upsert_projects(self, rows: list):
        """批量 upsert 项目到 projects_cqggzy 表（URL 去重）"""
        if not rows:
            return
        conn = self._get_conn().conn
        try:
            cols = [
                "url", "title", "category", "info_type", "business_type",
                "publish_date", "publish_date_raw", "content_preview", "full_content",
                "budget", "bid_amount", "deadline", "region", "industry",
                "tender_type", "project_overview", "bidder_requirements",
                "submission_deadline", "contact_name", "contact_phone", "contact_email",
                "attachments_count", "attachments", "keywords_matched",
                "source_url", "scraped_at", "scraped_by",
                "contract_amount", "planned_publish_date", "tender_content",
            ]
            placeholders = ",".join(["%s"] * len(cols))
            set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols[1:])
            insert_sql = f"""
                INSERT INTO projects_cqggzy ({','.join(cols)})
                VALUES ({placeholders})
                ON CONFLICT (url) DO UPDATE SET
                    {set_clause}
            """
            from psycopg2.extras import execute_batch
            execute_batch(conn.cursor(), insert_sql, rows, page_size=500)
            conn.commit()
            logger.debug(f"upsert_projects: {len(rows)} rows")
        except Exception as e:
            conn.rollback()
            logger.error(f"upsert_projects: {e}")


    def _init_tables(self):
        if USE_PG:
            # PG schema is created by migration script
            # Migration: add user_id column to favorites if missing
            c = self._get_conn()
            try:
                c.execute("SELECT user_id FROM favorites LIMIT 1")
            except Exception:
                try:
                    c.execute("ALTER TABLE favorites ADD COLUMN user_id TEXT DEFAULT ''")
                    c.execute("CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id)")
                    c.execute("CREATE INDEX IF NOT EXISTS idx_favorites_title ON favorites(title)")
                    logger.info("Migrated PG favorites table: added user_id column and title index")
                except Exception as e:
                    logger.warning(f"PG favorites migration skipped: {e}")
            return
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
            "CREATE INDEX IF NOT EXISTS idx_qualifications_name ON bidder_qualifications(name);",
            "CREATE INDEX IF NOT EXISTS idx_qualifications_category ON bidder_qualifications(category);",
            "CREATE INDEX IF NOT EXISTS idx_qualifications_status ON bidder_qualifications(status);",
            "CREATE INDEX IF NOT EXISTS idx_qualifications_valid_to ON bidder_qualifications(valid_to);",
            "CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_logs(event);",
            "CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id);",
            "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp);",
            "CREATE INDEX IF NOT EXISTS idx_keywords_category ON keywords(category);",
            "CREATE INDEX IF NOT EXISTS idx_keywords_enabled ON keywords(enabled);",
            "CREATE INDEX IF NOT EXISTS idx_tasks_user ON collection_tasks(user_id);",
            "CREATE INDEX IF NOT EXISTS idx_tasks_status ON collection_tasks(status);",
            "CREATE INDEX IF NOT EXISTS idx_executions_task ON task_executions(task_id);",
        ]
        for idx in indexes:
            c.execute(idx)
        c.commit()

    # ── Config Backups ───────────────────────────────────────────────────────

    def backup_config(
        self, version_label: str, config_data: dict, description: str = ""
    ) -> bool:
        """保存配置备份"""
        import json, time

        c = self._get_conn()
        try:
            c.execute(
                "INSERT INTO config_backups(version_label, config_data, description, created_at) VALUES (?, ?, ?, ?)",
                (
                    version_label,
                    json.dumps(config_data, ensure_ascii=False),
                    description,
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            c.commit()
            return True
        except Exception as e:
            logger.error(f"backup_config: {e}")
            return False

    def get_config_backups(self, limit: int = 10) -> list:
        """获取配置备份列表"""
        import json

        c = self._get_conn()
        try:
            rows = c.execute(
                "SELECT id, version_label, description, created_at FROM config_backups ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_config_backups: {e}")
            return []

    def restore_config(self, backup_id: str) -> dict:
        """恢复配置备份"""
        import json

        c = self._get_conn()
        try:
            row = c.execute(
                "SELECT * FROM config_backups WHERE id = ?", (backup_id,)
            ).fetchone()
            if not row:
                return None
            data = json.loads(row["config_data"])
            for key, value in data.items():
                c.execute(
                    "INSERT INTO config(config_key, config_value) VALUES (%s, %s) ON CONFLICT (config_key) DO UPDATE SET config_value=EXCLUDED.config_value",
                    (key, json.dumps(value, ensure_ascii=False)),
                )
            c.commit()
            return dict(row)
        except Exception as e:
            logger.error(f"restore_config: {e}")
            return None

    # ── Batch Writer ──────────────────────────────────────────────────────────

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
                conn.execute(_convert_placeholders(sql), params or None)
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"_execute_batch: {e}")

    def _pg_execute(self, conn, sql, params=None):
        """Execute SQL on PostgreSQL, converting ? placeholders to %s."""
        if params is None:
            return conn.execute(_convert_placeholders(sql))
        return conn.execute(_convert_placeholders(sql), params)

    def close(self):
        self._shutdown = True
        if hasattr(self._local, "pg_conn") and self._local.pg_conn:
            try:
                self._local.pg_conn.rollback()
            except Exception:
                pass
            _pg_close_conn(self._local.pg_conn)
            self._local.pg_conn = None


_db_instance = None
_db_lock = threading.Lock()


def get_db() -> Database:
    global _db_instance
    if _db_instance is None:
        with _db_lock:
            if _db_instance is None:
                _db_instance = Database()
    return _db_instance
