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
from typing import Dict, List, Optional

from loguru import logger

from app.constants import BatchConstants
from app.database.tables import (
    AnnotationsMixin,
    FavoritesMixin,
    ModalsMixin,
    NotificationsMixin,
    QualificationsMixin,
    UsersMixin,
    KeywordsMixin,
    ProjectsMixin,
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
    ProjectsMixin,
    NotificationsMixin,
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

    def upsert_project_overview(self, url: str, project_overview: str) -> None:
        """按 URL 更新 project_overview（采集流程调用）"""
        if not url or not project_overview:
            return
        try:
            conn = self._get_conn()
            conn.execute(
                "UPDATE projects_cqggzy SET project_overview = %s WHERE url = %s",
                (project_overview, url),
            )
            conn.commit()
        except Exception as e:
            logger.warning(f"upsert_project_overview: {e}")

    def update_detail_fields(self, url: str, fields: dict) -> None:
        """按 URL 更新详情相关字段 (2026-06-12 增强: 写 6 字段防 6-10 重复 BUG)
        字段 (任选):
          - full_content: 详情页正文
          - content_preview: 摘要 (≤500 字)
          - info_type: 招标公告/采购公告/招标计划/中标候选人公示/...
          - publish_date: 发布日期 (YYYY-MM-DD 字符串)
          - project_no: 项目编号
          - keywords_matched: 关键词 (逗号分隔)
        """
        if not url or not fields:
            return
        # 过滤空值 (None / "") — 避免用空值覆盖已有数据
        valid = {k: v for k, v in fields.items()
                 if v is not None and v != "" and k in {
                     "full_content", "content_preview", "info_type",
                     "publish_date", "project_no", "keywords_matched"
                 }}
        if not valid:
            return
        try:
            conn = self._get_conn()
            set_clause = ", ".join([f"{k} = %s" for k in valid.keys()])
            sql = f"UPDATE projects_cqggzy SET {set_clause} WHERE url = %s"
            conn.execute(sql, list(valid.values()) + [url])
            conn.commit()
        except Exception as e:
            logger.warning(f"update_detail_fields: {e}")

    def update_full_content(self, url: str, full_content: str, content_preview: str) -> None:
        """[保留兼容] 按 URL 更新 full_content 和 content_preview, 转调 update_detail_fields"""
        return self.update_detail_fields(url, {
            "full_content": full_content,
            "content_preview": content_preview,
        })

    
    def get_latest_projects(self, limit: int = 1000) -> list:
        """2026-07-01 PR: 拉取最新 N 条项目 (按 scraped_at DESC).

        用于 /api/projects/latest 端点的 DB fallback.
        L1/L2 cache 命中时跳过此方法 (走 in-memory slice).
        """
        conn = self._get_conn()
        if USE_PG:
            sql = """
                SELECT * FROM (
                    SELECT url, title, category, info_type, business_type, publish_date,
                           publish_date_raw, content_preview, full_content, budget, bid_amount,
                           deadline, region, industry, tender_type, project_overview,
                           bidder_requirements, submission_deadline, contact_name,
                           contact_phone, contact_email, attachments_count, attachments,
                           keywords_matched, source_url, scraped_at, scraped_by,
                           contract_amount, planned_publish_date, tender_content, project_no
                    FROM projects_cqggzy
                    UNION ALL
                    SELECT url, title, category, info_type, business_type, publish_date,
                           publish_date_raw, content_preview, full_content, budget, bid_amount,
                           deadline, region, industry, tender_type, project_overview,
                           bidder_requirements, submission_deadline, contact_name,
                           contact_phone, contact_email, attachments_count, attachments,
                           keywords_matched, source_url, scraped_at, scraped_by,
                           contract_amount, planned_publish_date, tender_content, project_no
                    FROM projects_ccgp
                    UNION ALL
                    SELECT url, title, category, info_type, business_type, publish_date,
                           publish_date_raw, content_preview, full_content, budget, bid_amount,
                           deadline, region, industry, tender_type, project_overview,
                           bidder_requirements, submission_deadline, contact_name,
                           contact_phone, contact_email, attachments_count, attachments,
                           keywords_matched, source_url, scraped_at, scraped_by,
                           contract_amount, planned_publish_date, tender_content, project_no
                    FROM projects_fahcqmu
                ) AS combined
                ORDER BY scraped_at DESC NULLS LAST
                LIMIT %s
            """
        else:
            sql = """
                SELECT * FROM (
                    SELECT url, title, category, info_type, business_type, publish_date,
                           publish_date_raw, content_preview, full_content, budget, bid_amount,
                           deadline, region, industry, tender_type, project_overview,
                           bidder_requirements, submission_deadline, contact_name,
                           contact_phone, contact_email, attachments_count, attachments,
                           keywords_matched, source_url, scraped_at, scraped_by,
                           contract_amount, planned_publish_date, tender_content, project_no
                    FROM projects_cqggzy
                    UNION ALL
                    SELECT url, title, category, info_type, business_type, publish_date,
                           publish_date_raw, content_preview, full_content, budget, bid_amount,
                           deadline, region, industry, tender_type, project_overview,
                           bidder_requirements, submission_deadline, contact_name,
                           contact_phone, contact_email, attachments_count, attachments,
                           keywords_matched, source_url, scraped_at, scraped_by,
                           contract_amount, planned_publish_date, tender_content, project_no
                    FROM projects_ccgp
                    UNION ALL
                    SELECT url, title, category, info_type, business_type, publish_date,
                           publish_date_raw, content_preview, full_content, budget, bid_amount,
                           deadline, region, industry, tender_type, project_overview,
                           bidder_requirements, submission_deadline, contact_name,
                           contact_phone, contact_email, attachments_count, attachments,
                           keywords_matched, source_url, scraped_at, scraped_by,
                           contract_amount, planned_publish_date, tender_content, project_no
                    FROM projects_fahcqmu
                )
                ORDER BY scraped_at DESC
                LIMIT ?
            """
        try:
            rows = conn.execute(sql, (limit,)).fetchall()
            return [dict(r) if not isinstance(r, dict) else r for r in rows]
        except Exception as e:
            logger.error(f"[get_latest_projects] DB error limit={limit}: {e}")
            return []

    def upsert_projects(self, rows: list):
        """批量 upsert 项目到 projects_cqggzy 表（URL 去重）

        rows: list of dict or list of tuple. dicts are converted to tuples using col order.
        """
        if not rows:
            return
        conn = self._get_conn().conn
        # 2026-07-07 fix: 入口 rollback 清理 thread-local 缓存 conn 可能携带的 aborted state
        # _get_conn() 用 self._local 缓存 conn, 跨 method 跨 function 复用同一 conn
        # 之前 method 异常后, conn 状态可能未完全清理 (autocommit=False 下 idle in transaction)
        # 不在入口 rollback 的话, execute_batch 第一条 SQL 就报 'current transaction is aborted'
        try:
            conn.rollback()
        except Exception:
            pass
        # 保留原始 dict rows 用于关联表同步（在 convert tuple 后会丢失字段名）
        rows_original = [r for r in rows if isinstance(r, dict)]
        # 2026-07-07 fix: 用 try/finally 确保 conn 放回 pool, 避免 idle in transaction 堆积
        # 历史 bug: conn._get_conn() 拿了没 putconn, 池 min=5 max=50, 全泄漏后阻塞 DDL
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
                "project_no",  # 2026-06-10 修复: Bug 4 真凶 — cols 列表缺 project_no 导致 row dict 里的 project_no 被忽略
            ]
            placeholders = ",".join(["%s"] * len(cols))
            # 2026-06-05 修复：保护 full_content/content_preview 不被空值覆盖
            # 列表 API 不返回 content，upsert 会用空值覆盖已填的详情正文，导致每周期丢失 ~7700 条详情
            # 2026-06-26 修复（F3）：scraped_at 改用 CASE WHEN 保护（NULLIF 在 TIMESTAMP 字段报错）
            # 与 projects_fahcqmu (db.py:526) 修复方式对齐
            text_protected_cols = {"full_content", "content_preview"}
            timestamp_protected_cols = {"scraped_at"}
            set_parts = []
            for c in cols[1:]:
                if c in text_protected_cols:
                    set_parts.append(
                        f"{c}=COALESCE(NULLIF(EXCLUDED.{c}, ''), projects_cqggzy.{c})"
                    )
                elif c in timestamp_protected_cols:
                    set_parts.append(
                        f"{c}=CASE WHEN EXCLUDED.{c} IS NOT NULL "
                        f"THEN EXCLUDED.{c} ELSE projects_cqggzy.{c} END"
                    )
                else:
                    set_parts.append(f"{c}=EXCLUDED.{c}")
            set_clause = ", ".join(set_parts)
            insert_sql = f"""
                INSERT INTO projects_cqggzy ({','.join(cols)})
                VALUES ({placeholders})
                ON CONFLICT (url) DO UPDATE SET
                    {set_clause}
            """
            from psycopg2.extras import execute_batch

            # Convert dict rows to tuples if needed, preserving None for NULL columns
            if rows and isinstance(rows[0], dict):
                # Columns that allow NULL (datetime, date, integer)
                null_cols = {'deadline', 'publish_date', 'attachments_count', 'opening_date', 'scraped_at'}
                def _to_val(r, c):
                    v = r.get(c)
                    if v is None or v == "":
                        return None
                    return v if c in null_cols else (v or "")
                rows = [[_to_val(r, c) for c in cols] for r in rows]

            execute_batch(conn.cursor(), insert_sql, rows, page_size=500)
            conn.commit()
            logger.debug(f"upsert_projects: {len(rows)} rows")
        except Exception as e:
            conn.rollback()
            logger.error(f"upsert_projects: {e}")
        finally:
            # 关键: 始终把 conn 放回 pool, 无论成功失败
            try:
                _pg_close_conn(conn)
            except Exception:
                pass

        # 联动写入 projects + project_records 关联表
        try:
            self._sync_projects_link(rows_original, source_table="projects_cqggzy")
        except Exception as e:
            logger.warning(f"_sync_projects_link (cqggzy) failed: {e}")


    def upsert_projects_ccgp(self, rows: list):
        """批量 upsert 项目到 projects_ccgp 表（URL 去重）"""
        if not rows:
            return
        conn = self._get_conn().conn
        # 保留原始 dict rows 用于关联表同步
        rows_original = [r for r in rows if isinstance(r, dict)]
        try:
            cols = [
                "url", "title", "category", "info_type", "publish_date", "publish_date_raw",
                "content_preview", "full_content", "budget", "bid_amount", "deadline",
                "region", "industry", "tender_type", "project_overview", "bidder_requirements",
                "submission_deadline", "contact_name", "contact_phone", "contact_email",
                "attachments_count", "attachments", "keywords_matched",
                "source_url", "scraped_at", "scraped_by",
                "contract_amount", "planned_publish_date", "tender_content",
                "project_no",
            ]
            placeholders = ",".join(["%s"] * len(cols))
            # 2026-06-05 修复：保护 full_content/content_preview 不被空值覆盖
            # 列表 API 不返回 content，upsert 会用空值覆盖已填的详情正文
            # 2026-06-27 修复 (P2 3.12): scraped_at 改用 CASE WHEN 保护
            # NULLIF 在 TIMESTAMP 字段报错 (PG 类型不匹配), 与 cqggzy/fahcqmu 统一
            text_protected_cols = {"full_content", "content_preview"}
            timestamp_protected_cols = {"scraped_at"}
            set_parts = []
            for c in cols[1:]:
                if c in text_protected_cols:
                    set_parts.append(
                        f"{c}=COALESCE(NULLIF(EXCLUDED.{c}, ''), projects_ccgp.{c})"
                    )
                elif c in timestamp_protected_cols:
                    set_parts.append(
                        f"{c}=CASE WHEN EXCLUDED.{c} IS NOT NULL "
                        f"THEN EXCLUDED.{c} ELSE projects_ccgp.{c} END"
                    )
                else:
                    set_parts.append(f"{c}=EXCLUDED.{c}")
            set_clause = ", ".join(set_parts)
            insert_sql = f"""
                INSERT INTO projects_ccgp ({','.join(cols)})
                VALUES ({placeholders})
                ON CONFLICT (url) DO UPDATE SET
                    {set_clause}
            """
            from psycopg2.extras import execute_batch

            if rows and isinstance(rows[0], dict):
                null_cols = {'deadline', 'publish_date', 'attachments_count', 'opening_date', 'scraped_at'}
                def _to_val(r, c):
                    v = r.get(c)
                    if v is None or v == "":
                        return None
                    return v if c in null_cols else (v or "")
                rows = [[_to_val(r, c) for c in cols] for r in rows]

            execute_batch(conn.cursor(), insert_sql, rows, page_size=500)
            conn.commit()
            logger.debug(f"upsert_projects_ccgp: {len(rows)} rows")
        except Exception as e:
            conn.rollback()
            logger.error(f"upsert_projects_ccgp: {e}")

        # 联动写入 projects + project_records 关联表
        try:
            self._sync_projects_link(rows_original, source_table="projects_ccgp")
        except Exception as e:
            logger.warning(f"_sync_projects_link (ccgp) failed: {e}")


    # ============================================================================
    # 2026-07-02: CCGP 采购意向 / 需求调查 (cherry-pick from feat/ccgp-intention-demand-2026-07-01)
    # 表: projects_ccgp_intention_demand (migration 004)
    # 采集器: app.crawlers.ccgp_intent_demand.CcgpIntentDemandCrawler
    # 触发: /api/internal/ccgp-collect (admin)
    # ============================================================================
    def upsert_projects_ccgp_intention_demand(self, rows: list):
        """批量 upsert 项目到 projects_ccgp_intention_demand 表 (URL 去重)

        字段: url / title / category / info_type / business_type / publish_date /
              content_preview / full_content / tender_content / budget / attachments /
              keywords_matched / source_url / scraped_at / source_id / source_type 等
        保护字段: full_content / content_preview / tender_content (CASE WHEN 空字符串保护)
        """
        if not rows:
            return
        conn = self._get_conn().conn
        rows_original = [r for r in rows if isinstance(r, dict)]
        try:
            cols = [
                "url", "title", "category", "info_type", "business_type",
                "publish_date", "publish_date_raw", "content_preview", "full_content",
                "budget", "bid_amount", "region", "industry", "tender_type",
                "project_overview", "bidder_requirements",
                "submission_deadline", "submission_location",
                "contact_name", "contact_phone", "contact_email",
                "attachments_count", "attachments", "keywords_matched",
                "source_url", "scraped_at", "scraped_by",
                "contract_amount", "planned_publish_date", "tender_content", "project_no",
                "source_id", "source_type",
            ]
            placeholders = ",".join(["%s"] * len(cols))
            text_protected_cols = {"full_content", "content_preview", "tender_content"}
            timestamp_protected_cols = {"scraped_at"}
            set_parts = []
            for c in cols[1:]:
                if c in text_protected_cols:
                    set_parts.append(
                        f"{c}=CASE WHEN EXCLUDED.{c} IS NOT NULL AND EXCLUDED.{c} <> '' "
                        f"THEN EXCLUDED.{c} ELSE projects_ccgp_intention_demand.{c} END"
                    )
                elif c in timestamp_protected_cols:
                    set_parts.append(
                        f"{c}=CASE WHEN EXCLUDED.{c} IS NOT NULL "
                        f"THEN EXCLUDED.{c} ELSE projects_ccgp_intention_demand.{c} END"
                    )
                else:
                    set_parts.append(f"{c}=EXCLUDED.{c}")
            set_clause = ", ".join(set_parts)
            insert_sql = f"""
                INSERT INTO projects_ccgp_intention_demand ({','.join(cols)})
                VALUES ({placeholders})
                ON CONFLICT (url) DO UPDATE SET
                    {set_clause}
            """
            from psycopg2.extras import execute_batch

            if rows and isinstance(rows[0], dict):
                null_cols = {'deadline', 'publish_date', 'attachments_count',
                             'opening_date', 'scraped_at', 'source_type'}
                jsonb_cols = {'attachments'}
                def _to_val(r, c):
                    v = r.get(c)
                    if v is None or v == "":
                        return None
                    if c in jsonb_cols:
                        if isinstance(v, (list, dict)) and len(v) == 0:
                            return None
                        import json
                        return json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                    return v if c in null_cols else (v or "")
                rows = [[_to_val(r, c) for c in cols] for r in rows]

            execute_batch(conn.cursor(), insert_sql, rows, page_size=500)
            conn.commit()
            logger.debug(f"upsert_projects_ccgp_intention_demand: {len(rows)} rows")
        except Exception as e:
            conn.rollback()
            logger.error(f"upsert_projects_ccgp_intention_demand: {e}")
            raise

        # 联动写入 projects + project_records 关联表
        try:
            self._sync_projects_link(rows_original, source_table="projects_ccgp_intention_demand")
        except Exception as e:
            logger.warning(f"_sync_projects_link (ccgp_intention_demand) failed: {e}")


    # ============================================================================
    # 2026-06-25: 重医附一院采集 (fahcqmu)
    # PR #39: feat/fahcqmu-crawler
    # ============================================================================
    def upsert_projects_fahcqmu(self, rows: list):
        """两阶段 upsert (Phase 1 dry-run INSERT + Phase 2 UPDATE)

        修复 execute_batch 单事务失败级联 → 全部 batch abort
        Phase 1: INSERT ... ON CONFLICT (url) DO NOTHING (新行写入, 已存在跳过)
        Phase 2: UPDATE 全字段 (CASE WHEN 保护 full_content/content_preview)
        每行 SAVEPOINT, 单行失败不波及其他行
        2026-07-20 修: attachments (jsonb) 空 dict/list/str → None (避免 `{} or ""` 给 JSONB 喂 '')

        rows: list of dict, 字段映射到 projects_fahcqmu 列 (35 cols)
        """
        if not rows:
            return
        conn = self._get_conn().conn
        # 2026-07-21 修: 连接池返还的 connection 可能残留 aborted 状态
        # (上一轮 cron 失败后 _pg_pool.putconn 未 rollback, 下次再取到同样的 conn
        # 第一个 execute 就被 "current transaction is aborted" 拒掉)
        # 先 rollback 清干净再开 cursor
        try:
            conn.rollback()
        except Exception:
            pass
        rows_original = [r for r in rows if isinstance(r, dict)]
        cur = conn.cursor()

        cols = [
            "url", "title", "category", "info_type", "business_type", "org_unit",
            "publish_date", "publish_date_raw", "content_preview", "full_content",
            "budget", "bid_amount", "deadline", "opening_date",
            "region", "industry", "tender_type", "project_overview",
            "bidder_requirements", "submission_deadline", "submission_location",
            "contact_name", "contact_phone", "contact_email",
            "attachments_count", "attachments", "keywords_matched",
            "source_url", "scraped_at", "scraped_by",
            "contract_amount", "planned_publish_date", "tender_content",
            "project_no",
        ]
        null_cols = {'deadline', 'publish_date', 'attachments_count',
                     'opening_date', 'scraped_at'}

        def _val(r, c):
            from psycopg2.extras import Json
            v = r.get(c)
            # JSONB: 空 dict/list/str → None (修 bug: `{} or ""` 给 JSONB 喂 '')
            # 非空 dict/list → Json() 适配器 (psycopg2 cursor 不会自动 dict→JSONB)
            if c == "attachments":
                if v in (None, "", [], {}):
                    return None
                return Json(v)
            if v is None or v == "":
                return None
            return v if c in null_cols else (v or "")

        # ===== Phase 1: dry-run INSERT (新建行) =====
        insert_sql = (f"INSERT INTO projects_fahcqmu ({','.join(cols)}) "
                      f"VALUES ({','.join(['%s']*len(cols))}) "
                      f"ON CONFLICT (url) DO NOTHING")
        p1_ok = p1_fail = 0
        for r in rows_original:
            url = r.get("url")
            try:
                cur.execute("SAVEPOINT sp_p1")
                cur.execute(insert_sql, [_val(r, c) for c in cols])
                cur.execute("RELEASE SAVEPOINT sp_p1")
                p1_ok += 1
            except Exception as e:
                cur.execute("ROLLBACK TO SAVEPOINT sp_p1")
                p1_fail += 1
                logger.warning(f"fahcqmu P1 fail url={url}: {e}")
        conn.commit()
        logger.debug(f"upsert_projects_fahcqmu P1: ok={p1_ok} fail={p1_fail}/{len(rows_original)}")

        # ===== Phase 2: UPDATE (刷新详情) =====
        # 2026-07-21 修: 加 timestamp_protected, scraped_at 不能被 NULL 覆盖 (避免 pipeline 不带 scraped_at 时把老值刷成 NULL)
        text_protected = {"full_content", "content_preview"}
        timestamp_protected = {"scraped_at"}
        set_parts = []
        for c in cols[1:]:
            if c in text_protected:
                set_parts.append(f"{c}=CASE WHEN %s IS NOT NULL AND %s<>'' THEN %s ELSE {c} END")
            elif c in timestamp_protected:
                set_parts.append(f"{c}=CASE WHEN %s IS NOT NULL THEN %s ELSE {c} END")
            else:
                set_parts.append(f"{c}=%s")
        update_sql = f"UPDATE projects_fahcqmu SET {', '.join(set_parts)} WHERE url=%s"

        p2_ok = p2_fail = 0
        for r in rows_original:
            url = r.get("url")
            params = []
            for c in cols[1:]:
                v = _val(r, c)
                if c in text_protected:
                    params.extend([v, v, v])
                elif c in timestamp_protected:
                    params.extend([v, v])
                else:
                    params.append(v)
            params.append(url)
            try:
                cur.execute("SAVEPOINT sp_p2")
                cur.execute(update_sql, params)
                cur.execute("RELEASE SAVEPOINT sp_p2")
                p2_ok += 1
            except Exception as e:
                cur.execute("ROLLBACK TO SAVEPOINT sp_p2")
                p2_fail += 1
                logger.warning(f"fahcqmu P2 fail url={url}: {e}")
        conn.commit()
        logger.debug(f"upsert_projects_fahcqmu P2: ok={p2_ok} fail={p2_fail}/{len(rows_original)}")

        cur.close()

        # 联动写入 projects + project_records 关联表
        try:
            self._sync_projects_link(rows_original, source_table="projects_fahcqmu")
        except Exception as e:
            logger.warning(f"_sync_projects_link (fahcqmu) failed: {e}")

    def upsert_projects_cqyc(self, rows: list):
        """批量 upsert 项目到 projects_cqyc 表（URL 去重）

        rows: list of dict, 字段映射到 projects_cqyc 列:
            url, title, category, info_type, business_type, publish_date,
            content_preview, full_content, budget, region, industry,
            tender_type, contact_name, contact_phone, contact_email,
            project_no, scraped_at, source_url

        幂等写入: ON CONFLICT (url) DO UPDATE (不覆盖非空字段)
        """
        if not rows:
            logger.debug("upsert_projects_cqyc: 空 rows, 跳过")
            return 0

        cols = [
            "url", "title", "category", "info_type", "business_type",
            "publish_date", "content_preview", "full_content", "budget",
            "region", "industry", "tender_type", "contact_name",
            "contact_phone", "contact_email", "project_no",
            "scraped_at", "source_url"
        ]

        placeholders = ",".join(["%s"] * len(cols))
        update_cols = ", ".join([f"{c} = EXCLUDED.{c}" for c in cols if c not in ("url", "scraped_at")])

        # 保护已填的详情字段：如果旧值非空且新值空，保留旧值
        # 注意: DATE 类型 (publish_date) 不能用 <> '' 检查 (会报 InvalidDatetimeFormat)
        protect_fields_text = ["full_content", "content_preview", "info_type", "project_no"]
        protect_fields_date = ["publish_date"]
        for f in protect_fields_text:
            update_cols = update_cols.replace(
                f"{f} = EXCLUDED.{f}",
                f"{f} = CASE WHEN projects_cqyc.{f} IS NOT NULL AND projects_cqyc.{f} <> '' THEN projects_cqyc.{f} ELSE EXCLUDED.{f} END"
            )
        for f in protect_fields_date:
            update_cols = update_cols.replace(
                f"{f} = EXCLUDED.{f}",
                f"{f} = CASE WHEN projects_cqyc.{f} IS NOT NULL THEN projects_cqyc.{f} ELSE EXCLUDED.{f} END"
            )

        conn = self._get_conn()
        cur = conn.cursor()
        # DATE 类型字段: 空字符串 → None (否则 PG 报 InvalidDatetimeFormat)
        date_cols = {"publish_date"}
        try:
            values = []
            for row in rows:
                val_tuple = tuple(
                    (None if c in date_cols and (row.get(c, "") == "" or row.get(c) is None) else row.get(c, ""))
                    for c in cols
                )
                values.append(val_tuple)

            insert_sql = f"""
                INSERT INTO projects_cqyc ({','.join(cols)})
                VALUES ({placeholders})
                ON CONFLICT (url) DO UPDATE SET {update_cols}
            """
            from psycopg2.extras import execute_batch
            execute_batch(cur, insert_sql, values, page_size=100)
            conn.commit()
            logger.debug(f"upsert_projects_cqyc: {len(rows)} rows")
        except Exception as e:
            conn.rollback()
            logger.error(f"upsert_projects_cqyc: {e}")
            raise

        # 联动写入 projects + project_records 关联表
        try:
            self._sync_projects_link(rows, source_table="projects_cqyc")
        except Exception as e:
            logger.warning(f"_sync_projects_link (cqyc) failed: {e}")

    # ━━━ Delta Sync (DataCache v4 增量加载) ━━━
    def delta_load_since(self, since_ts: Optional[str] = None, limit_per_table: int = 5000) -> List[dict]:
        """DataCache v4 增量加载: 读取 updated_at > since_ts 的所有项目 (跨 3 表).

        Args:
            since_ts: ISO 格式时间戳字符串 (e.g. "2026-06-29 11:00:00").
                     None 或 "" 表示全表加载 (启动首次加载用).
            limit_per_table: 每张表最大返回行数 (防爆, 默认 5000).

        Returns:
            List[dict]: 项目字典列表, 字段与 _load_projects row_to_project 一致.
                       按 url 去重 (URL 是 3 表唯一键, 但 union 可能产生重复, 用 dict 兜底).

        性能:
            - 有 since_ts: 走 idx_*_updated_at 索引 (~5ms, 通常 <100 行)
            - since_ts=None: 全表 seq scan (~2.9s, 仅启动时)

        应用场景:
            1. DataCache v4 get_main() L1 miss/TTL 失效时, 取代全表 108k 加载
            2. catnum 失效触发增量同步时
        """
        # where 条件: 有 since_ts 时按 updated_at 过滤
        if since_ts:
            where_clause = "WHERE updated_at > %s"
            params = (since_ts,)
            limit_clause = f"LIMIT {int(limit_per_table)}"
        else:
            # 全量加载 (cold start): 不加 LIMIT (各表最大 ~107k)
            where_clause = ""
            params = None
            limit_clause = ""

        results: Dict[str, dict] = {}  # url -> dict (去重)
        tables = ("projects_cqggzy", "projects_ccgp", "projects_ccgp_intention_demand", "projects_fahcqmu", "projects_cqyc")

        try:
            conn = self._get_conn()
            cur = conn.cursor()
            for tbl in tables:
                sql = f"SELECT * FROM {tbl} {where_clause} ORDER BY updated_at ASC {limit_clause}"
                cur.execute(sql, params)
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description] if hasattr(cur, "description") and cur.description else None
                if not cols:
                    continue
                for row in rows:
                    if hasattr(row, "keys"):
                        d = dict(row)
                    else:
                        d = dict(zip(cols, row))
                    # 复用 _load_projects row_to_project 字段映射
                    p = self._delta_row_to_project(d, tbl)
                    url = p.get("url")
                    if url and url not in results:
                        results[url] = p
            cur.close()
        except Exception as e:
            logger.warning(f"[delta_load_since] DB 错误: {e}")

        out = list(results.values())
        logger.info(
            f"[delta_load_since] since={since_ts or 'FULL'} tables={tables} "
            f"返回 {len(out)} 条 (limit_per_table={limit_per_table if since_ts else 'NONE'})"
        )
        return out

    def _delta_row_to_project(self, d: dict, tbl: str) -> dict:
        """将单行映射为标准 project dict (与 projects.py row_to_project 一致).

        注意: 这里故意不复用 projects.py 的 row_to_project, 因为那是 local 闭包.
              保持独立, 未来如果 schema 变动可以快速同步.
        """
        # updated_at 是字符串 (e.g. "2026-06-29 11:00:00.123456")
        # delta_sync 用它做时间戳比较, 必须保留在 dict 里
        updated_at = d.get("updated_at")
        return {
            "title": d.get("title", ""),
            "type": d.get("category", ""),
            "publish_date": str(d.get("publish_date", "")) if d.get("publish_date") else "",
            "publish_date_raw": d.get("publish_date_raw", ""),
            "url": d.get("url", ""),
            "source_url": d.get("source_url") or d.get("url", ""),
            "content_preview": (d.get("content_preview") or "").replace("\n", " "),
            "budget": d.get("budget", ""),
            "deadline": str(d.get("deadline", "")) if d.get("deadline") else "",
            "region": d.get("region", ""),
            "tender_type": d.get("tender_type", ""),
            "keywords_matched": d.get("keywords_matched", ""),
            "contact_name": d.get("contact_name", ""),
            "contact_phone": d.get("contact_phone", ""),
            "contact_email": d.get("contact_email", ""),
            "attachments_count": d.get("attachments_count", 0) or 0,
            "attachments": d.get("attachments", "[]"),
            "scraped_at": str(d.get("created_at", "")) if d.get("created_at") else "",
            "scraped_by": d.get("scraped_by", ""),
            "business_type": d.get("business_type", ""),
            "info_type": d.get("info_type", ""),
            "project_no": d.get("project_no", ""),
            "project_overview": (d.get("project_overview") or "").replace("\n", " "),
            "bidder_requirements": d.get("bidder_requirements", ""),
            "submission_deadline": d.get("submission_deadline", ""),
            "bid_amount": d.get("bid_amount", ""),
            "full_content": d.get("full_content", "") or "",
            "tender_content": d.get("tender_content", "") or "",
            "_table": tbl,  # delta sync 内部用, 不暴露给 API
            "_updated_at": str(updated_at) if updated_at else "",  # delta sync 时间戳
        }


    def upsert_bid_results(self, rows: list) -> int:
        """批量 upsert 中标结果到 bid_results 表.

        rows: list of dict, 字段: source, project_id, url, info_type, category,
              package_no, winner_name, winner_rank, bid_amount, bid_amount_num,
              winner_score, publish_date

        返回: 写入条数.

        ⚠️ 内存 dedup 与 DB UNIQUE 约束语义差 (P2 3.13):
        - 内存 dedup key: (source, project_id, package_no, cleaned_winner_name OR winner_name)
        - DB UNIQUE:        (source, project_id, package_no, cleaned_winner_name)
        - 当 cleaned_winner_name 为 NULL/'' 时, dedup 回退用 winner_name, 但 PG 对 NULL
          的 UNIQUE 语义是 "NULL != NULL", 所以同 (source, pid, pno) 的不同 winner_name
          记录 (均 cleaned_winner_name=NULL) 不会被 UNIQUE 约束拦截, 可能产生语义重复行.
        - 推荐修复: DB 端给 cleaned_winner_name 加 NOT NULL 约束, 或将 dedup key 下沉到
          DB 层 (COALESCE in UNIQUE index). 本次只文档化, 不动 schema/逻辑.
        """
        if not rows:
            return 0
        conn = self._get_conn().conn
        try:
            from psycopg2.extras import execute_values

            # 按 UNIQUE 约束去重 (同 batch 内重复会触发 DO UPDATE conflict)
            # 2026-06-27 修复：唯一约束已改用 cleaned_winner_name (PR #40), 这里必须同步用 cleaned_winner_name
            # 不然 ON CONFLICT 找不到匹配的 UNIQUE 约束 → "there is no unique or exclusion constraint matching"
            seen = set()
            values = []
            for r in rows:
                # 用 cleaned_winner_name 作为去重 key; 若未传入, 回退 winner_name
                # (PR #41 已让 bid_parser 写 cleaned_winner_name, 但旧 pipeline 调用可能没传)
                dedup_key = r.get('cleaned_winner_name') or r.get('winner_name') or ''
                key = (r.get('source', 'cqggzy'), r['project_id'], r['package_no'], dedup_key)
                if key in seen:
                    continue
                seen.add(key)
                values.append((
                    r.get('source', 'cqggzy'),
                    r['project_id'],
                    r['url'],
                    r['info_type'],
                    r.get('category', ''),
                    r['package_no'],
                    r['winner_name'],
                    # 2026-06-27 修复：补传 cleaned_winner_name (PR #40 加的列, PR #41 应用层写, 但 db 层一直没接)
                    r.get('cleaned_winner_name') or None,
                    r['winner_rank'],
                    r['bid_amount'],
                    r['bid_amount_num'],
                    r['winner_score'],
                    r['publish_date'],
                ))

            if not values:
                return 0

            insert_sql = """
                INSERT INTO bid_results (
                  source, project_id, url, info_type, category, package_no,
                  winner_name, cleaned_winner_name, winner_rank, bid_amount, bid_amount_num,
                  winner_score, publish_date
                )
                VALUES %s
                ON CONFLICT (source, project_id, package_no, cleaned_winner_name)
                DO UPDATE SET
                  info_type = EXCLUDED.info_type,
                  category = EXCLUDED.category,
                  winner_name = EXCLUDED.winner_name,
                  -- 2026-06-27 修复：保护已存在的 cleaned_winner_name, 避免空值覆盖手工填值
                  cleaned_winner_name = COALESCE(NULLIF(EXCLUDED.cleaned_winner_name, ''), bid_results.cleaned_winner_name),
                  winner_rank = EXCLUDED.winner_rank,
                  bid_amount = EXCLUDED.bid_amount,
                  bid_amount_num = EXCLUDED.bid_amount_num,
                  winner_score = EXCLUDED.winner_score,
                  publish_date = EXCLUDED.publish_date,
                  parsed_at = NOW()
            """
            execute_values(conn.cursor(), insert_sql, values, page_size=200)
            conn.commit()
            logger.debug(f"upsert_bid_results: {len(values)} rows")
            return len(values)
        except Exception as e:
            conn.rollback()
            logger.error(f"upsert_bid_results: {e}")
            return 0


    def _init_tables(self):
        if USE_PG:
            # PG schema is created by migration script
            c = self._get_conn()
            # Migration: add user_id column to favorites if missing
            try:
                c.execute("SELECT user_id FROM favorites LIMIT 1")
            except Exception:
                try:
                    c.rollback()
                    c.execute("ALTER TABLE favorites ADD COLUMN user_id TEXT DEFAULT ''")
                    c.execute("CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id)")
                    c.execute("CREATE INDEX IF NOT EXISTS idx_favorites_title ON favorites(title)")
                    logger.info("Migrated PG favorites table: added user_id column and title index")
                except Exception as e:
                    logger.warning(f"PG favorites migration skipped: {e}")
                    c.rollback()
            # Migration: create projects + project_records if not exists
            try:
                c.execute("SELECT id FROM projects LIMIT 1")
            except Exception:
                c.rollback()
                c.execute("""CREATE TABLE IF NOT EXISTS projects (
                    id SERIAL PRIMARY KEY,
                    project_name VARCHAR(500) NOT NULL,
                    project_name_raw VARCHAR(500) NOT NULL,
                    project_no VARCHAR(100) DEFAULT NULL UNIQUE,
                    business_type VARCHAR(50) DEFAULT '',
                    region VARCHAR(100) DEFAULT '',
                    industry VARCHAR(100) DEFAULT '',
                    budget VARCHAR(100) DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")
                c.execute("CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(project_name)")
                c.execute("CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at)")
                c.execute("""CREATE TABLE IF NOT EXISTS project_records (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    record_url TEXT NOT NULL UNIQUE,
                    record_type VARCHAR(50) DEFAULT '',
                    title VARCHAR(500) DEFAULT '',
                    publish_date TEXT DEFAULT '',
                    budget VARCHAR(100) DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")
                c.execute("CREATE INDEX IF NOT EXISTS idx_project_records_project ON project_records(project_id)")
                c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_project_records_url ON project_records(record_url)")
                logger.info("Created projects + project_records tables")
            else:
                # Migration: ensure record_url has UNIQUE constraint (required for ON CONFLICT)
                try:
                    cur2 = c.cursor()
                    cur2.execute("""SELECT 1 FROM pg_indexes
                                     WHERE indexname='idx_project_records_url'
                                       AND indexdef LIKE '%UNIQUE%'""")
                    has_unique = cur2.fetchone() is not None
                    if not has_unique:
                        c.execute("DROP INDEX IF EXISTS idx_project_records_url")
                        c.execute("CREATE UNIQUE INDEX idx_project_records_url ON project_records(record_url)")
                        logger.info("Migrated: idx_project_records_url → UNIQUE")
                except Exception as e:
                    logger.warning(f"record_url UNIQUE migration skipped: {e}")
                    c.rollback()
            # Migration: create notifications table (2026-06-06 收藏项目关联提醒)
            try:
                c.execute("SELECT id FROM notifications LIMIT 1")
            except Exception:
                c.rollback()
                c.execute("""CREATE TABLE IF NOT EXISTS notifications (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT '',
                    project_id INTEGER NOT NULL,
                    record_id INTEGER NOT NULL,
                    project_name TEXT DEFAULT '',
                    info_type TEXT DEFAULT '',
                    record_url TEXT DEFAULT '',
                    record_title TEXT DEFAULT '',
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    telegram_chat_id TEXT DEFAULT '',
                    telegram_msg_id TEXT DEFAULT '',
                    dedup_key TEXT DEFAULT ''
                )""")
                c.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, sent_at)")
                c.execute("CREATE INDEX IF NOT EXISTS idx_notifications_dedup ON notifications(dedup_key, sent_at)")
                c.execute("CREATE INDEX IF NOT EXISTS idx_notifications_project ON notifications(project_id)")
                logger.info("Created notifications table")
            # Migration: add user_id to duplicate_records if missing
            try:
                c.execute("SELECT user_id FROM duplicate_records LIMIT 1")
            except Exception:
                try:
                    c.execute("ALTER TABLE duplicate_records ADD COLUMN user_id TEXT DEFAULT ''")
                    c.execute("DROP INDEX IF EXISTS idx_duplicates_canonical")
                    c.execute("CREATE INDEX IF NOT EXISTS idx_duplicates_canonical ON duplicate_records(user_id, canonical_url)")
                    logger.info("Migrated PG duplicate_records: added user_id column")
                except Exception as e:
                    logger.warning(f"PG duplicate_records migration skipped: {e}")
            c.commit()
            return
        c = self._get_conn()
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS favorites(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '',
                project_url TEXT NOT NULL,
                title TEXT NOT NULL,
                source_url TEXT DEFAULT '',
                tender_type TEXT DEFAULT '',
                budget TEXT DEFAULT '',
                publish_date TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, project_url)
            );
            CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id);
            CREATE INDEX IF NOT EXISTS idx_favorites_url ON favorites(project_url);
            CREATE INDEX IF NOT EXISTS idx_favorites_title ON favorites(title);
            CREATE INDEX IF NOT EXISTS idx_favorites_updated ON favorites(updated_at);
            CREATE INDEX IF NOT EXISTS idx_favorites_status ON favorites(status);
            """
        )
        # Migration: add user_id column to existing favorites table (runs after CREATE TABLE)
        try:
            c.execute("SELECT user_id FROM favorites LIMIT 1")
        except Exception:
            c.execute("ALTER TABLE favorites ADD COLUMN user_id TEXT DEFAULT ''")
            logger.info("Migrated favorites table: added user_id column")
        # Migration: add user_id to duplicate_records
        try:
            c.execute("SELECT user_id FROM duplicate_records LIMIT 1")
        except Exception:
            c.execute("ALTER TABLE duplicate_records ADD COLUMN user_id TEXT DEFAULT ''")
            logger.info("Migrated duplicate_records table: added user_id column")
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS annotations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_url TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT "",
                priority TEXT DEFAULT "normal",
                tags TEXT DEFAULT "[]",
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            -- 2026-06-11 添加: 补全 UNIQUE 约束, 配合 add_annotation 的 ON CONFLICT (project_url) DO UPDATE
            CREATE UNIQUE INDEX IF NOT EXISTS idx_annotations_project_url_unique ON annotations(project_url);
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
                user_id TEXT NOT NULL DEFAULT '',
                canonical_url TEXT NOT NULL,
                duplicate_url TEXT NOT NULL,
                duplicate_title TEXT DEFAULT '',
                similarity_score REAL DEFAULT 0,
                detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, canonical_url, duplicate_url)
            );
            CREATE TABLE IF NOT EXISTS data_cache(
                cache_key TEXT PRIMARY KEY,
                cache_value TEXT NOT NULL,
                expires_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS crawler_configs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                base_url TEXT NOT NULL,
                list_selector TEXT DEFAULT "",
                item_rules TEXT DEFAULT "{}",
                pagination_type TEXT DEFAULT "none",
                pagination_selector TEXT DEFAULT "",
                pagination_param TEXT DEFAULT "",
                filter_keyword TEXT DEFAULT "",
                cookies TEXT DEFAULT "",
                headers TEXT DEFAULT "{}",
                status TEXT DEFAULT "active",
                business_type TEXT DEFAULT "",
                info_type TEXT DEFAULT "",
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS crawl_executions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                config_id INTEGER NOT NULL,
                status TEXT DEFAULT "running",
                items_found INTEGER DEFAULT 0,
                items_new INTEGER DEFAULT 0,
                error_message TEXT DEFAULT "",
                started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT DEFAULT "",
                FOREIGN KEY (config_id) REFERENCES crawler_configs(id)
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
            CREATE TABLE IF NOT EXISTS config(
                config_key TEXT PRIMARY KEY,
                config_value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_logs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event VARCHAR(50) NOT NULL,
                user_id VARCHAR(100),
                ip_address VARCHAR(45),
                user_agent TEXT,
                resource VARCHAR(500),
                result VARCHAR(20),
                details TEXT DEFAULT '{}',
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS collection_tasks(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id VARCHAR(100) NOT NULL,
                name TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT DEFAULT 'idle',
                schedule_type TEXT DEFAULT 'manual',
                schedule_cron TEXT DEFAULT '',
                keywords TEXT DEFAULT '[]',
                exclude_keywords TEXT DEFAULT '[]',
                info_types TEXT DEFAULT '[]',
                budget_min REAL,
                priority INTEGER DEFAULT 5,
                max_concurrency INTEGER DEFAULT 5,
                request_interval REAL DEFAULT 2.0,
                timeout_seconds INTEGER DEFAULT 30,
                items_found INTEGER DEFAULT 0,
                items_new INTEGER DEFAULT 0,
                last_run_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS task_executions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                status TEXT DEFAULT 'running',
                items_found INTEGER DEFAULT 0,
                items_new INTEGER DEFAULT 0,
                error_message TEXT DEFAULT '',
                started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT,
                duration_ms INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS keywords(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL UNIQUE,
                category TEXT DEFAULT 'include',
                match_mode TEXT DEFAULT 'exact',
                threshold REAL DEFAULT 0.8,
                enabled INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS projects(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name VARCHAR(500) NOT NULL,
                project_name_raw VARCHAR(500) NOT NULL,
                project_no VARCHAR(100) DEFAULT NULL UNIQUE,
                business_type VARCHAR(50) DEFAULT '',
                region VARCHAR(100) DEFAULT '',
                industry VARCHAR(100) DEFAULT '',
                budget VARCHAR(100) DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS project_records(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                record_url TEXT NOT NULL UNIQUE,
                record_type VARCHAR(50) DEFAULT '',
                title VARCHAR(500) DEFAULT '',
                publish_date TEXT DEFAULT '',
                budget VARCHAR(100) DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
        """
        )
        c.commit()
        self._init_indexes()
        self._init_projects_table()

    def _init_indexes(self):
        c = self._get_conn()
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_favorites_url ON favorites(project_url);",
            "CREATE INDEX IF NOT EXISTS idx_favorites_status ON favorites(status);",
            "CREATE INDEX IF NOT EXISTS idx_favorites_updated ON favorites(updated_at);",
            "CREATE INDEX IF NOT EXISTS idx_annotations_url ON annotations(project_url);",
            "CREATE INDEX IF NOT EXISTS idx_logs_level ON scrape_logs(log_level);",
            "CREATE INDEX IF NOT EXISTS idx_logs_created ON scrape_logs(created_at);",
            "CREATE INDEX IF NOT EXISTS idx_duplicates_canonical ON duplicate_records(user_id, canonical_url);",
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
