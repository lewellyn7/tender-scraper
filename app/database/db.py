"""SQLite 数据库 - 优化版

已拆分为表模块：
  - app.database.tables.favorites        : favorites 表
  - app.database.tables.annotations      : annotations 表
  - app.database.tables.qualifications  : bidder_qualifications 表
  - app.database.tables.users           : users 表
  - app.database.tables.modals           : filter_presets / logs / duplicates / cache / backup / stats / schema
"""

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

from app.constants import BatchConstants
from app.database.tables import (
    AnnotationsMixin,
    FavoritesMixin,
    ModalsMixin,
    QualificationsMixin,
    UsersMixin,
)

DB_PATH = Path(__file__).parent.parent.parent / "config" / "tender_scraper.db"


class Database(
    FavoritesMixin,
    AnnotationsMixin,
    QualificationsMixin,
    UsersMixin,
    ModalsMixin,
):
    """SQLite 数据库单例（混合了所有表操作Mixin）"""

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
            CREATE TABLE IF NOT EXISTS bidder_qualifications(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(200) NOT NULL,
                category VARCHAR(50) DEFAULT '',
                level VARCHAR(20) DEFAULT '',
                certificate_no VARCHAR(100) DEFAULT '',
                valid_from TEXT,
                valid_to TEXT,
                issuer VARCHAR(200) DEFAULT '',
                file_path VARCHAR(500) DEFAULT '',
                linked_tenders TEXT DEFAULT '[]',
                status VARCHAR(20) DEFAULT '有效',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
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
            "CREATE INDEX IF NOT EXISTS idx_qualifications_name ON bidder_qualifications(name);",
            "CREATE INDEX IF NOT EXISTS idx_qualifications_category ON bidder_qualifications(category);",
            "CREATE INDEX IF NOT EXISTS idx_qualifications_status ON bidder_qualifications(status);",
            "CREATE INDEX IF NOT EXISTS idx_qualifications_valid_to ON bidder_qualifications(valid_to);",
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
