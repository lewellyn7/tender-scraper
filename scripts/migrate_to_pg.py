#!/usr/bin/env python3
"""
SQLite → PostgreSQL 迁移脚本
用法: python scripts/migrate_to_pg.py [--dry-run]
"""
import argparse
import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg


def get_sqlite_conn():
    db_path = Path(__file__).parent.parent / "config" / "tender_scraper.db"
    return sqlite3.connect(str(db_path))


def get_pg_url():
    return os.getenv(
        "DATABASE_URL",
        "postgresql://root:YOUR_DB_PASSWORD_HERE@localhost:5435/tender_scraper"
    )


# ── Schema DDL ───────────────────────────────────────────────────────────────
DDL = """
-- annotations
CREATE TABLE IF NOT EXISTS annotations(
    id SERIAL PRIMARY KEY,
    project_url TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    priority TEXT DEFAULT 'normal',
    tags TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_annotations_url ON annotations(project_url);

-- bidder_qualifications
CREATE TABLE IF NOT EXISTS bidder_qualifications(
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    category VARCHAR(50) DEFAULT '',
    level VARCHAR(20) DEFAULT '',
    region VARCHAR(50) DEFAULT '',
    qualification_number VARCHAR(100) DEFAULT '',
    valid_from DATE DEFAULT NULL,
    valid_until DATE DEFAULT NULL,
    status VARCHAR(20) DEFAULT 'active',
    contact_name VARCHAR(100) DEFAULT '',
    contact_phone VARCHAR(50) DEFAULT '',
    contact_email VARCHAR(100) DEFAULT '',
    registered_capital DECIMAL(15,2) DEFAULT NULL,
    main_categories TEXT DEFAULT '',
    description TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- config
CREATE TABLE IF NOT EXISTS config(
    config_key TEXT PRIMARY KEY,
    config_value TEXT NOT NULL
);

-- filter_presets
CREATE TABLE IF NOT EXISTS filter_presets(
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    preset_key TEXT UNIQUE NOT NULL,
    filter_config TEXT NOT NULL,
    is_default SMALLINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_presets_key ON filter_presets(preset_key);

-- favorites
CREATE TABLE IF NOT EXISTS favorites(
    id SERIAL PRIMARY KEY,
    project_url TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    source_url TEXT DEFAULT '',
    tender_type TEXT DEFAULT '',
    budget TEXT DEFAULT '',
    publish_date TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_favorites_url ON favorites(project_url);
CREATE INDEX IF NOT EXISTS idx_favorites_status ON favorites(status);
CREATE INDEX IF NOT EXISTS idx_favorites_updated ON favorites(updated_at);

-- users
CREATE TABLE IF NOT EXISTS users(
    id SERIAL PRIMARY KEY,
    user_id TEXT UNIQUE NOT NULL,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email VARCHAR(255) DEFAULT '',
    role TEXT DEFAULT 'user',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP DEFAULT NULL
);

-- scrape_logs
CREATE TABLE IF NOT EXISTS scrape_logs(
    id SERIAL PRIMARY KEY,
    log_level TEXT NOT NULL,
    message TEXT NOT NULL,
    source TEXT DEFAULT 'system',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_logs_level_time ON scrape_logs(log_level, created_at);
CREATE INDEX IF NOT EXISTS idx_logs_level ON scrape_logs(log_level);
CREATE INDEX IF NOT EXISTS idx_logs_created ON scrape_logs(created_at);

-- duplicate_records
CREATE TABLE IF NOT EXISTS duplicate_records(
    id SERIAL PRIMARY KEY,
    canonical_url TEXT NOT NULL,
    duplicate_url TEXT NOT NULL,
    duplicate_title TEXT DEFAULT '',
    similarity_score REAL DEFAULT 0,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_duplicates_canonical ON duplicate_records(canonical_url);

-- data_cache
CREATE TABLE IF NOT EXISTS data_cache(
    cache_key TEXT PRIMARY KEY,
    cache_value TEXT NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- config_backups
CREATE TABLE IF NOT EXISTS config_backups(
    id SERIAL PRIMARY KEY,
    version_label TEXT NOT NULL,
    config_data TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- schema_version
CREATE TABLE IF NOT EXISTS schema_version(
    version INTEGER PRIMARY KEY
);
"""


async def create_schema(pool):
    """Create all tables"""
    print("Creating PostgreSQL schema...")
    async with pool.acquire() as conn:
        await conn.execute(DDL)
    print("Schema created.")


def sqlite_to_pg_value(val):
    """Convert SQLite value to PostgreSQL-compatible value"""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, str):
        return val
    return str(val)


async def migrate_table(pool, table_name, columns, dry_run=False):
    """Migrate a single table from SQLite to PostgreSQL"""
    sqlite_conn = get_sqlite_conn()
    cursor = sqlite_conn.execute(f"SELECT * FROM {table_name}")
    
    rows = cursor.fetchall()
    if not rows:
        print(f"  {table_name}: 0 rows, skipped")
        sqlite_conn.close()
        return
    
    col_names = [desc[0] for desc in cursor.description]
    col_placeholders = ', '.join([f'${i+1}' for i in range(len(col_names))])
    
    total = len(rows)
    print(f"  {table_name}: {total} rows...")
    
    if dry_run:
        sqlite_conn.close()
        return
    
    migrated = 0
    errors = 0
    
    for row in rows:
        values = [sqlite_to_pg_value(v) for v in row]
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    f"INSERT INTO {table_name} ({', '.join(col_names)}) VALUES ({col_placeholders}) ON CONFLICT DO NOTHING",
                    values
                )
            migrated += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"    Error: {e}")
    
    print(f"  {table_name}: {migrated} migrated, {errors} errors")
    sqlite_conn.close()


async def migrate(dry_run=False):
    url = get_pg_url()
    print(f"Connecting to PostgreSQL: {url}")
    
    # Connect and create database if not exists
    sys_db_url = url.rsplit('/', 1)[0] + '/postgres'
    try:
        sys_conn = await asyncpg.connect(sys_db_url)
        db_name = url.rsplit('/', 1)[1]
        exists = await sys_conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", db_name
        )
        if not exists:
            await sys_conn.execute(f'CREATE DATABASE "{db_name}"')
            print(f"Created database: {db_name}")
        await sys_conn.close()
    except Exception as e:
        print(f"Warning: could not check/create database: {e}")
    
    pool = await asyncpg.create_pool(url, min_size=1, max_size=5)
    
    try:
        await create_schema(pool)
        
        tables = [
            ("config", ["config_key", "config_value"]),
            ("users", ["id", "user_id", "username", "password_hash", "email", "role", "created_at", "last_login"]),
            ("filter_presets", ["id", "name", "preset_key", "filter_config", "is_default", "created_at"]),
            ("favorites", ["id", "project_url", "title", "source_url", "tender_type", "budget", "publish_date", "status", "created_at", "updated_at"]),
            ("annotations", ["id", "project_url", "note", "priority", "tags", "created_at", "updated_at"]),
            ("bidder_qualifications", None),  # Full schema
            ("scrape_logs", ["id", "log_level", "message", "source", "created_at"]),
            ("duplicate_records", ["id", "canonical_url", "duplicate_url", "duplicate_title", "similarity_score", "detected_at"]),
            ("data_cache", ["cache_key", "cache_value", "expires_at", "created_at"]),
            ("config_backups", ["id", "version_label", "config_data", "description", "created_at"]),
            ("schema_version", ["version"]),
        ]
        
        for table_name, cols in tables:
            try:
                if cols is None:
                    cols = [desc[0] for desc in sqlite3.connect(get_sqlite_conn().dbpath if hasattr(get_sqlite_conn(), 'dbpath') else "").execute(f"PRAGMA table_info({table_name})").fetchall()]
                await migrate_table(pool, table_name, cols, dry_run)
            except Exception as e:
                print(f"  {table_name}: Error - {e}")
        
        # Verify
        async with pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM favorites")
            print(f"\n✅ Migration complete. favorites count in PG: {count}")
        
    finally:
        await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    
    asyncio.run(migrate(args.dry_run))
