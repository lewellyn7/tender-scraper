-- ============================================================
-- PostgreSQL 全量初始化脚本
-- tender-scraper 完整表结构 + pgvector 扩展
-- 执行: docker compose exec -T postgres psql -U postgres -d postgres -f /docker-entrypoint-initdb.d/init_pg.sql
--       或: docker compose exec -T postgres psql -U postgres -d postgres -f /tmp/init_pg.sql
-- ============================================================

-- 1. 创建扩展（需 superuser）
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. 切换到业务库（如未在命令行指定）
-- \c tender_scraper;

-- ============================================================
-- 向量存储表（pgvector）
-- ============================================================
CREATE TABLE IF NOT EXISTS vector_store (
    id SERIAL PRIMARY KEY,
    doc_id VARCHAR(255) UNIQUE NOT NULL,   -- 文档唯一标识
    text TEXT NOT NULL,                     -- 向量化文本内容
    metadata JSONB DEFAULT '{}',           -- 附加元数据
    embedding vector(384) NOT NULL,         -- 384维向量（all-MiniLM-L6-v2）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS vector_store_embedding_idx ON vector_store USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS vector_store_doc_id_idx ON vector_store(doc_id);

-- ============================================================
-- favorites（收藏项目）
-- ============================================================
CREATE TABLE IF NOT EXISTS favorites(
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL DEFAULT '',
    project_url TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    source_url TEXT DEFAULT '',
    tender_type TEXT DEFAULT '',
    budget TEXT DEFAULT '',
    publish_date TEXT DEFAULT '',
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id);
CREATE INDEX IF NOT EXISTS idx_favorites_title ON favorites(title);
CREATE INDEX IF NOT EXISTS idx_favorites_updated ON favorites(updated_at);
CREATE INDEX IF NOT EXISTS idx_favorites_status ON favorites(status);
CREATE INDEX IF NOT EXISTS idx_favorites_url ON favorites(project_url);

-- ============================================================
-- keywords（关键词）
-- ============================================================
CREATE TABLE IF NOT EXISTS keywords(
    id SERIAL PRIMARY KEY,
    keyword VARCHAR(255) NOT NULL,
    category VARCHAR(50) DEFAULT '',
    match_mode VARCHAR(20) DEFAULT 'exact',  -- exact/fuzzy/partial
    threshold REAL DEFAULT 0.8,
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_keywords_keyword ON keywords(keyword);
CREATE INDEX IF NOT EXISTS idx_keywords_enabled ON keywords(enabled);

-- ============================================================
-- annotations（标注）
-- ============================================================
CREATE TABLE IF NOT EXISTS annotations(
    id SERIAL PRIMARY KEY,
    project_url TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    priority VARCHAR(20) DEFAULT 'normal',
    tags JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- 2026-06-11 添加: 补全 UNIQUE 约束, 配合 add_annotation 的 ON CONFLICT (project_url) DO UPDATE
CREATE UNIQUE INDEX IF NOT EXISTS idx_annotations_project_url_unique ON annotations(project_url);
CREATE INDEX IF NOT EXISTS idx_annotations_project ON annotations(project_url);

-- ============================================================
-- filter_presets（筛选预设）
-- ============================================================
CREATE TABLE IF NOT EXISTS filter_presets(
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    preset_key VARCHAR(100) UNIQUE NOT NULL,
    filter_config JSONB NOT NULL,
    is_default INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- users（用户）
-- ============================================================
CREATE TABLE IF NOT EXISTS users(
    user_id VARCHAR(100) PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    display_name VARCHAR(100) DEFAULT '',
    role VARCHAR(20) DEFAULT 'viewer',
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP
);

-- ============================================================
-- audit_logs（审计日志）
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_logs(
    id SERIAL PRIMARY KEY,
    event VARCHAR(50) NOT NULL,
    user_id VARCHAR(100),
    ip_address VARCHAR(45),
    user_agent TEXT,
    resource VARCHAR(500),
    result VARCHAR(20),
    details JSONB,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_logs(event);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp DESC);

-- ============================================================
-- bidder_qualifications（投标人资质）
-- ============================================================
CREATE TABLE IF NOT EXISTS bidder_qualifications(
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    category VARCHAR(50) DEFAULT '',
    level VARCHAR(20) DEFAULT '',
    certificate_no VARCHAR(100) DEFAULT '',
    valid_from TIMESTAMP,
    valid_to TIMESTAMP,
    issuer VARCHAR(200) DEFAULT '',
    file_path VARCHAR(500) DEFAULT '',
    linked_tenders JSONB DEFAULT '[]',
    status VARCHAR(20) DEFAULT '有效',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_bq_status ON bidder_qualifications(status);
CREATE INDEX IF NOT EXISTS idx_bq_valid_to ON bidder_qualifications(valid_to);

-- ============================================================
-- collection_tasks（采集任务）
-- ============================================================
CREATE TABLE IF NOT EXISTS collection_tasks(
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(100),
    name VARCHAR(200) NOT NULL,
    source VARCHAR(100) DEFAULT '',
    status VARCHAR(20) DEFAULT 'idle',
    schedule_type VARCHAR(20) DEFAULT 'cron',
    schedule_cron VARCHAR(100) DEFAULT '',
    keywords JSONB DEFAULT '[]',
    exclude_keywords JSONB DEFAULT '[]',
    info_types JSONB DEFAULT '[]',
    budget_min REAL DEFAULT 0,
    priority INTEGER DEFAULT 0,
    max_concurrency INTEGER DEFAULT 3,
    request_interval REAL DEFAULT 1.0,
    timeout_seconds INTEGER DEFAULT 30,
    items_found INTEGER DEFAULT 0,
    items_new INTEGER DEFAULT 0,
    last_run_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- task_executions（任务执行记录）
-- ============================================================
CREATE TABLE IF NOT EXISTS task_executions(
    id SERIAL PRIMARY KEY,
    task_id INTEGER REFERENCES collection_tasks(id),
    status VARCHAR(20) DEFAULT 'running',
    items_found INTEGER DEFAULT 0,
    items_new INTEGER DEFAULT 0,
    error_message TEXT DEFAULT '',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    duration_ms INTEGER
);

-- ============================================================
-- crawl_executions（采集执行记录）
-- ============================================================
CREATE TABLE IF NOT EXISTS crawl_executions(
    id SERIAL PRIMARY KEY,
    config_id INTEGER REFERENCES crawler_configs(id),
    status VARCHAR(20) DEFAULT 'running',
    items_found INTEGER DEFAULT 0,
    items_new INTEGER DEFAULT 0,
    error_message TEXT DEFAULT '',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP
);

-- ============================================================
-- crawler_configs（爬虫配置）
-- ============================================================
CREATE TABLE IF NOT EXISTS crawler_configs(
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    base_url TEXT NOT NULL,
    list_selector TEXT DEFAULT '',
    item_rules JSONB DEFAULT '{}',
    pagination_type VARCHAR(20) DEFAULT 'none',
    pagination_selector TEXT DEFAULT '',
    pagination_param TEXT DEFAULT '',
    filter_keyword TEXT DEFAULT '',
    cookies TEXT DEFAULT '',
    headers JSONB DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'active',
    business_type VARCHAR(50) DEFAULT '',
    info_type VARCHAR(50) DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- duplicate_records（重复记录）
-- ============================================================
CREATE TABLE IF NOT EXISTS duplicate_records(
    id SERIAL PRIMARY KEY,
    canonical_url TEXT NOT NULL,
    duplicate_url TEXT NOT NULL,
    duplicate_title TEXT DEFAULT '',
    similarity_score REAL DEFAULT 0,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_dup_canonical ON duplicate_records(canonical_url);

-- ============================================================
-- data_cache（缓存）
-- ============================================================
CREATE TABLE IF NOT EXISTS data_cache(
    cache_key VARCHAR(255) PRIMARY KEY,
    cache_value TEXT NOT NULL,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- config（配置）
-- ============================================================
CREATE TABLE IF NOT EXISTS config(
    config_key VARCHAR(100) PRIMARY KEY,
    config_value TEXT NOT NULL
);

-- ============================================================
-- config_backups（配置备份）
-- ============================================================
CREATE TABLE IF NOT EXISTS config_backups(
    id SERIAL PRIMARY KEY,
    version_label VARCHAR(100) NOT NULL,
    config_data JSONB NOT NULL,
    description TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- schema_version（版本记录）
-- ============================================================
CREATE TABLE IF NOT EXISTS schema_version(
    version INTEGER PRIMARY KEY
);
INSERT INTO schema_version (version) VALUES (1) ON CONFLICT DO NOTHING;

-- ============================================================
-- projects（项目主档 - 招标信息聚合）
-- ============================================================
CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    project_name VARCHAR(500) NOT NULL,          -- 项目名称（规范化后）
    project_name_raw VARCHAR(500) NOT NULL,      -- 原始项目名称（含"一期"等）
    project_no VARCHAR(100) DEFAULT '',           -- 项目编号（招标编号）
    business_type VARCHAR(50) DEFAULT '',         -- 业务类型：工程建设/政府采购
    region VARCHAR(100) DEFAULT '',               -- 地区
    industry VARCHAR(100) DEFAULT '',            -- 行业
    budget VARCHAR(100) DEFAULT '',               -- 总预算（汇总）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(project_name);
CREATE INDEX IF NOT EXISTS idx_projects_no ON projects(project_no);
CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at);

-- ============================================================
-- project_records（项目-记录关联表）
-- ============================================================
CREATE TABLE IF NOT EXISTS project_records (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    record_url TEXT NOT NULL,                    -- 关联的 harvest_records 或 favorites url
    record_type VARCHAR(50) DEFAULT '',          -- info_type：招标公告/答疑补遗/中标结果等
    title VARCHAR(500) DEFAULT '',
    publish_date TEXT DEFAULT '',
    budget VARCHAR(100) DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_project_records_project ON project_records(project_id);
CREATE INDEX IF NOT EXISTS idx_project_records_url ON project_records(record_url);

-- ============================================================
-- 验证 pgvector
-- ============================================================
SELECT 'pgvector extension ready' AS status,
       n.nspname AS schema,
       e.extname AS extension,
       e.extversion AS version
FROM pg_extension e
JOIN pg_namespace n ON n.oid = e.extnamespace
WHERE e.extname = 'vector';
