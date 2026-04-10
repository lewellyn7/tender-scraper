#!/usr/bin/env python3
"""
PostgreSQL 数据模型 — asyncpg 连接池 + CRUD
用于政府采购采集系统的数据持久化
"""

import json
import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import asyncpg

# ── 配置 ────────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://lewellyn:lewellyn@localhost:5432/procurement"
)
POOL_MIN_SIZE = int(os.getenv("DB_POOL_MIN_SIZE", "2"))
POOL_MAX_SIZE = int(os.getenv("DB_POOL_MAX_SIZE", "10"))


# ── 连接池 ──────────────────────────────────────────────
class DatabaseManager:
    _pool: Optional[asyncpg.Pool] = None

    @classmethod
    async def get_pool(cls) -> asyncpg.Pool:
        if cls._pool is None:
            cls._pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=POOL_MIN_SIZE,
                max_size=POOL_MAX_SIZE,
                command_timeout=30,
                max_queries=50000,
                max_inactive_connection_lifetime=300,
            )
        return cls._pool

    @classmethod
    async def close_pool(cls):
        if cls._pool:
            await cls._pool.close()
            cls._pool = None

    @classmethod
    @asynccontextmanager
    async def acquire(cls):
        """异步上下文管理器获取连接"""
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            yield conn

    @classmethod
    @asynccontextmanager
    async def transaction(cls):
        """事务上下文管理器"""
        async with cls.acquire() as conn:
            async with conn.transaction():
                yield conn


# ── 枚举 ────────────────────────────────────────────────
class RecordStatus(str, Enum):
    PENDING = "pending"       # 待处理
    PROCESSING = "processing"  # 处理中
    DONE = "done"            # 已完成
    FAILED = "failed"        # 失败


# ── 模型 ────────────────────────────────────────────────
class HarvestRecord:
    """采集记录模型"""

    table_name = "harvest_records"

    def __init__(
        self,
        title: str,
        source_url: str,
        source_name: str,
        publish_date: Optional[date] = None,
        matched_keywords: Optional[List[str]] = None,
        raw_data: Optional[Dict[str, Any]] = None,
        status: RecordStatus = RecordStatus.PENDING,
        retry_count: int = 0,
        id: Optional[int] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.id = id
        self.title = title
        self.source_url = source_url
        self.source_name = source_name
        self.publish_date = publish_date
        self.matched_keywords = matched_keywords or []
        self.raw_data = raw_data or {}
        self.status = status
        self.retry_count = retry_count
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "source_url": self.source_url,
            "source_name": self.source_name,
            "publish_date": self.publish_date.isoformat() if self.publish_date else None,
            "matched_keywords": self.matched_keywords,
            "raw_data": self.raw_data,
            "status": self.status.value if isinstance(self.status, RecordStatus) else self.status,
            "retry_count": self.retry_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_row(cls, row: asyncpg.Record) -> "HarvestRecord":
        rd = row.get("raw_data")
        raw_data = json.loads(rd) if isinstance(rd, str) else (rd or {})
        mk = row.get("matched_keywords")
        matched_keywords = json.loads(mk) if isinstance(mk, str) else (mk or [])
        status_val = row.get("status", "pending")
        try:
            status = RecordStatus(status_val)
        except ValueError:
            status = RecordStatus.PENDING
        return cls(
            id=row["id"],
            title=row["title"],
            source_url=row["source_url"],
            source_name=row["source_name"],
            publish_date=row.get("publish_date"),
            matched_keywords=matched_keywords,
            raw_data=raw_data,
            status=status,
            retry_count=row.get("retry_count", 0),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    # ── CRUD ───────────────────────────────────────────

    @classmethod
    async def create(cls, conn: asyncpg.Connection) -> "HarvestRecord":
        """插入新记录"""
        row = await conn.fetchrow(
            f"""
            INSERT INTO {cls.table_name}
                (title, source_url, source_name, publish_date,
                 matched_keywords, raw_data, status, retry_count,
                 created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING *
            """,
            cls.__name__,
            # We'll use a static method below that doesn't need self
        )
        # actual implementation uses classmethod below with explicit params
        raise NotImplementedError("Use create_with_values() instead")

    @classmethod
    async def create_with_values(
        cls,
        conn: asyncpg.Connection,
        title: str,
        source_url: str,
        source_name: str,
        publish_date: Optional[date] = None,
        matched_keywords: Optional[List[str]] = None,
        raw_data: Optional[Dict[str, Any]] = None,
        status: RecordStatus = RecordStatus.PENDING,
    ) -> "HarvestRecord":
        """插入新记录（静态方式）"""
        now = datetime.utcnow()
        row = await conn.fetchrow(
            f"""
            INSERT INTO {cls.table_name}
                (title, source_url, source_name, publish_date,
                 matched_keywords, raw_data, status, retry_count,
                 created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING *
            """,
            title,
            source_url,
            source_name,
            publish_date,
            json.dumps(matched_keywords or []),
            json.dumps(raw_data or {}),
            status.value,
            0,
            now,
            now,
        )
        return cls.from_row(row)

    @classmethod
    async def get_by_id(cls, conn: asyncpg.Connection, record_id: int) -> Optional["HarvestRecord"]:
        """根据 ID 查询"""
        row = await conn.fetchrow(
            f"SELECT * FROM {cls.table_name} WHERE id = $1", record_id
        )
        return cls.from_row(row) if row else None

    @classmethod
    async def get_by_url(cls, conn: asyncpg.Connection, source_url: str) -> Optional["HarvestRecord"]:
        """根据 URL 查重"""
        row = await conn.fetchrow(
            f"SELECT * FROM {cls.table_name} WHERE source_url = $1", source_url
        )
        return cls.from_row(row) if row else None

    @classmethod
    async def list_by_status(
        cls,
        conn: asyncpg.Connection,
        status: RecordStatus,
        limit: int = 100,
    ) -> List["HarvestRecord"]:
        """根据状态查询列表"""
        rows = await conn.fetch(
            f"""
            SELECT * FROM {cls.table_name}
            WHERE status = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            status.value,
            limit,
        )
        return [cls.from_row(r) for r in rows]

    @classmethod
    async def list_recent(
        cls,
        conn: asyncpg.Connection,
        source_name: Optional[str] = None,
        days: int = 7,
        limit: int = 200,
    ) -> List["HarvestRecord"]:
        """查询近期记录"""
        query = f"""
            SELECT * FROM {cls.table_name}
            WHERE created_at >= NOW() - INTERVAL '$1 days'
        """
        params = [days]
        if source_name:
            query += " AND source_name = $2"
            params.append(source_name)
        query += f" ORDER BY created_at DESC LIMIT ${len(params) + 1}"
        params.append(limit)
        rows = await conn.fetch(query, *params)
        return [cls.from_row(r) for r in rows]

    @classmethod
    async def update_status(
        cls,
        conn: asyncpg.Connection,
        record_id: int,
        status: RecordStatus,
    ) -> Optional["HarvestRecord"]:
        """更新状态"""
        row = await conn.fetchrow(
            f"""
            UPDATE {cls.table_name}
            SET status = $1, updated_at = NOW()
            WHERE id = $2
            RETURNING *
            """,
            status.value,
            record_id,
        )
        return cls.from_row(row) if row else None

    @classmethod
    async def increment_retry(cls, conn: asyncpg.Connection, record_id: int) -> None:
        """重试计数 +1"""
        await conn.execute(
            f"""
            UPDATE {cls.table_name}
            SET retry_count = retry_count + 1,
                updated_at = NOW(),
                status = $1
            WHERE id = $2
            """,
            RecordStatus.FAILED.value,
            record_id,
        )

    @classmethod
    async def upsert_by_url(
        cls,
        conn: asyncpg.Connection,
        title: str,
        source_url: str,
        source_name: str,
        publish_date: Optional[date] = None,
        matched_keywords: Optional[List[str]] = None,
        raw_data: Optional[Dict[str, Any]] = None,
    ) -> tuple["HarvestRecord", bool]:
        """
        插入或更新（根据 source_url 查重）。
        返回 (record, is_new) — is_new 表示是否新插入。
        """
        now = datetime.utcnow()
        existing = await cls.get_by_url(conn, source_url)
        if existing:
            # 更新
            row = await conn.fetchrow(
                f"""
                UPDATE {cls.table_name}
                SET title = $1, publish_date = $2,
                    matched_keywords = $3, raw_data = $4,
                    updated_at = $5, status = $6
                WHERE source_url = $7
                RETURNING *
                """,
                title,
                publish_date,
                json.dumps(matched_keywords or []),
                json.dumps(raw_data or {}),
                now,
                RecordStatus.PENDING.value,
                source_url,
            )
            return cls.from_row(row), False
        else:
            row = await conn.fetchrow(
                f"""
                INSERT INTO {cls.table_name}
                    (title, source_url, source_name, publish_date,
                     matched_keywords, raw_data, status, retry_count,
                     created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING *
                """,
                title,
                source_url,
                source_name,
                publish_date,
                json.dumps(matched_keywords or []),
                json.dumps(raw_data or {}),
                RecordStatus.PENDING.value,
                0,
                now,
                now,
            )
            return cls.from_row(row), True

    @classmethod
    async def delete_old(cls, conn: asyncpg.Connection, days: int = 90) -> int:
        """删除 N 天前的记录，返回删除数量"""
        result = await conn.execute(
            f"""
            DELETE FROM {cls.table_name}
            WHERE created_at < NOW() - INTERVAL '$1 days'
            AND status IN ($2, $3)
            """,
            days,
            RecordStatus.DONE.value,
            RecordStatus.FAILED.value,
        )
        # asyncpg.execute returns command tag like "DELETE N"
        count = int(result.split()[-1]) if result else 0
        return count


class SourceConfig:
    """数据来源配置模型"""

    table_name = "source_configs"

    def __init__(
        self,
        name: str,
        base_url: str,
        is_active: bool = True,
        keywords: Optional[List[str]] = None,
        rate_limit_rpm: int = 30,
        custom_headers: Optional[Dict[str, str]] = None,
        extra_config: Optional[Dict[str, Any]] = None,
        id: Optional[int] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.id = id
        self.name = name
        self.base_url = base_url
        self.is_active = is_active
        self.keywords = keywords or []
        self.rate_limit_rpm = rate_limit_rpm
        self.custom_headers = custom_headers or {}
        self.extra_config = extra_config or {}
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "is_active": self.is_active,
            "keywords": self.keywords,
            "rate_limit_rpm": self.rate_limit_rpm,
            "custom_headers": self.custom_headers,
            "extra_config": self.extra_config,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_row(cls, row: asyncpg.Record) -> "SourceConfig":
        kh = row.get("keywords")
        keywords = json.loads(kh) if isinstance(kh, str) else (kh or [])
        ch = row.get("custom_headers")
        custom_headers = json.loads(ch) if isinstance(ch, str) else (ch or {})
        ec = row.get("extra_config")
        extra_config = json.loads(ec) if isinstance(ec, str) else (ec or {})
        return cls(
            id=row["id"],
            name=row["name"],
            base_url=row["base_url"],
            is_active=row.get("is_active", True),
            keywords=keywords,
            rate_limit_rpm=row.get("rate_limit_rpm", 30),
            custom_headers=custom_headers,
            extra_config=extra_config,
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    # ── CRUD ───────────────────────────────────────────

    @classmethod
    async def create_with_values(
        cls,
        conn: asyncpg.Connection,
        name: str,
        base_url: str,
        is_active: bool = True,
        keywords: Optional[List[str]] = None,
        rate_limit_rpm: int = 30,
        custom_headers: Optional[Dict[str, str]] = None,
        extra_config: Optional[Dict[str, Any]] = None,
    ) -> "SourceConfig":
        now = datetime.utcnow()
        row = await conn.fetchrow(
            f"""
            INSERT INTO {cls.table_name}
                (name, base_url, is_active, keywords, rate_limit_rpm,
                 custom_headers, extra_config, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING *
            """,
            name,
            base_url,
            is_active,
            json.dumps(keywords or []),
            rate_limit_rpm,
            json.dumps(custom_headers or {}),
            json.dumps(extra_config or {}),
            now,
            now,
        )
        return cls.from_row(row)

    @classmethod
    async def get_by_id(cls, conn: asyncpg.Connection, cfg_id: int) -> Optional["SourceConfig"]:
        row = await conn.fetchrow(
            f"SELECT * FROM {cls.table_name} WHERE id = $1", cfg_id
        )
        return cls.from_row(row) if row else None

    @classmethod
    async def get_by_name(cls, conn: asyncpg.Connection, name: str) -> Optional["SourceConfig"]:
        row = await conn.fetchrow(
            f"SELECT * FROM {cls.table_name} WHERE name = $1", name
        )
        return cls.from_row(row) if row else None

    @classmethod
    async def list_active(cls, conn: asyncpg.Connection) -> List["SourceConfig"]:
        rows = await conn.fetch(
            f"SELECT * FROM {cls.table_name} WHERE is_active = true ORDER BY name"
        )
        return [cls.from_row(r) for r in rows]

    @classmethod
    async def upsert_by_name(
        cls,
        conn: asyncpg.Connection,
        name: str,
        base_url: str,
        is_active: bool = True,
        keywords: Optional[List[str]] = None,
        rate_limit_rpm: int = 30,
        custom_headers: Optional[Dict[str, str]] = None,
        extra_config: Optional[Dict[str, Any]] = None,
    ) -> tuple["SourceConfig", bool]:
        existing = await cls.get_by_name(conn, name)
        now = datetime.utcnow()
        if existing:
            row = await conn.fetchrow(
                f"""
                UPDATE {cls.table_name}
                SET base_url = $1, is_active = $2, keywords = $3,
                    rate_limit_rpm = $4, custom_headers = $5,
                    extra_config = $6, updated_at = $7
                WHERE name = $8
                RETURNING *
                """,
                base_url,
                is_active,
                json.dumps(keywords or []),
                rate_limit_rpm,
                json.dumps(custom_headers or {}),
                json.dumps(extra_config or {}),
                now,
                name,
            )
            return cls.from_row(row), False
        else:
            row = await conn.fetchrow(
                f"""
                INSERT INTO {cls.table_name}
                    (name, base_url, is_active, keywords, rate_limit_rpm,
                     custom_headers, extra_config, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING *
                """,
                name,
                base_url,
                is_active,
                json.dumps(keywords or []),
                rate_limit_rpm,
                json.dumps(custom_headers or {}),
                json.dumps(extra_config or {}),
                now,
                now,
            )
            return cls.from_row(row), True

    @classmethod
    async def deactivate(cls, conn: asyncpg.Connection, name: str) -> bool:
        result = await conn.execute(
            f"""
            UPDATE {cls.table_name}
            SET is_active = false, updated_at = NOW()
            WHERE name = $1
            """,
            name,
        )
        return result != "UPDATE 0"


# ── 初始化（创建表）──────────────────────────────────────
INIT_TABLES_SQL = """
DO $$ BEGIN
    CREATE TYPE harvest_record_status AS ENUM ('pending', 'processing', 'done', 'failed');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS harvest_records (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT NOT NULL,
    source_url      TEXT NOT NULL UNIQUE,
    source_name     TEXT NOT NULL,
    publish_date    DATE,
    matched_keywords JSONB DEFAULT '[]',
    raw_data        JSONB DEFAULT '{}',
    status          harvest_record_status NOT NULL DEFAULT 'pending',
    retry_count     INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_harvest_records_status
    ON harvest_records(status);
CREATE INDEX IF NOT EXISTS idx_harvest_records_source_name
    ON harvest_records(source_name);
CREATE INDEX IF NOT EXISTS idx_harvest_records_created_at
    ON harvest_records(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_harvest_records_publish_date
    ON harvest_records(publish_date DESC);

CREATE TABLE IF NOT EXISTS source_configs (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    base_url        TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    keywords        JSONB DEFAULT '[]',
    rate_limit_rpm  INTEGER NOT NULL DEFAULT 30,
    custom_headers  JSONB DEFAULT '{}',
    extra_config    JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_source_configs_is_active
    ON source_configs(is_active) WHERE is_active = true;
"""


async def init_tables(pool: Optional[asyncpg.Pool] = None) -> None:
    """初始化数据库表结构"""
    if pool:
        async with pool.acquire() as conn:
            await conn.execute(INIT_TABLES_SQL)
    else:
        async with DatabaseManager.acquire() as conn:
            await conn.execute(INIT_TABLES_SQL)


# ── 便捷入口 ─────────────────────────────────────────────
async def get_active_sources() -> List[SourceConfig]:
    """获取所有活跃数据源"""
    async with DatabaseManager.acquire() as conn:
        return await SourceConfig.list_active(conn)


async def save_harvest_records(
    records: List[Dict[str, Any]],
    source_name: str,
) -> tuple[int, int]:
    """
    批量保存采集记录（自动去重）。
    返回 (插入数, 更新数)。
    """
    inserted = updated = 0
    async with DatabaseManager.transaction() as conn:
        for r in records:
            _, is_new = await HarvestRecord.upsert_by_url(
                conn,
                title=r.get("title", ""),
                source_url=r.get("url", ""),
                source_name=source_name,
                publish_date=r.get("date"),
                matched_keywords=r.get("matched_keywords"),
                raw_data=r.get("raw_data"),
            )
            if is_new:
                inserted += 1
            else:
                updated += 1
    return inserted, updated


# ── 健康检查 ─────────────────────────────────────────────
async def health_check() -> Dict[str, Any]:
    """数据库健康状态检查"""
    try:
        async with DatabaseManager.acquire() as conn:
            version = await conn.fetchval("SELECT version()")
            record_count = await conn.fetchval(
                "SELECT COUNT(*) FROM harvest_records"
            )
            source_count = await conn.fetchval(
                "SELECT COUNT(*) FROM source_configs WHERE is_active = true"
            )
            return {
                "status": "ok",
                "postgres_version": version,
                "record_count": record_count,
                "active_source_count": source_count,
            }
    except Exception as e:
        return {"status": "error", "error": str(e)}
