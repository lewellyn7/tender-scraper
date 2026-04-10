-- ============================================================
-- harvest_records 和 source_configs 表初始化脚本
-- (已有 INIT_TABLES_SQL from async_models.py)
-- ============================================================

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
