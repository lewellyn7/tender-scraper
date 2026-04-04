"""DB"""
import sqlite3, json, threading
from pathlib import Path
from typing import Optional, List, Dict
from loguru import logger

DB_PATH = Path(__file__).parent.parent.parent / "config" / "tender_scraper.db"

class Database:
    _local = threading.local()
    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()
    def _get_conn(self):
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn
