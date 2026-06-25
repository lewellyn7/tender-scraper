-- ============================================================================
-- Migration 003: 重医附一院采集 - 创建 projects_fahcqmu 表
-- ============================================================================
-- 创建时间: 2026-06-25
-- 来源: PR #39 feat/fahcqmu-crawler
--
-- 重医附一院 (https://www.fahcqmu.cn) 公开招标采购信息:
--   - 信息数据处 (xxsjc1): 阳光推介 / 调研 / 采购公告 / 采购结果 (186 条)
--   - 总务处   (cgglczb2): 采购公告 / 采购结果 (1465 条)
--   - 其他     (qt):       16 条
--   合计首次全量: 1667 条
--
-- Schema 与 projects_ccgp 同构 (37 列), 额外加 org_unit 字段区分 3 个部门.
-- URL 唯一约束, 支持 ON CONFLICT (url) DO UPDATE 幂等写入.
-- ============================================================================

CREATE TABLE IF NOT EXISTS projects_fahcqmu (
    -- 主键
    id BIGSERIAL PRIMARY KEY,

    -- 唯一 URL (来自 fahcqmu.cn 列表)
    url TEXT UNIQUE NOT NULL,

    -- 基础字段 (与 projects_ccgp 对齐)
    title TEXT NOT NULL DEFAULT '',
    category TEXT DEFAULT '',
    info_type TEXT DEFAULT '',          -- ygtjgg / dygg / cggg / cgjggs / jggs / qt
    business_type TEXT DEFAULT '',      -- 医院采购
    publish_date DATE,
    publish_date_raw TEXT DEFAULT '',
    content_preview TEXT DEFAULT '',
    full_content TEXT DEFAULT '',
    budget TEXT DEFAULT '',
    bid_amount TEXT DEFAULT '',
    deadline TIMESTAMP,
    opening_date TIMESTAMP,
    region TEXT DEFAULT '',
    industry TEXT DEFAULT '',
    tender_type TEXT DEFAULT '',
    project_overview TEXT DEFAULT '',
    bidder_requirements TEXT DEFAULT '',
    submission_deadline TEXT DEFAULT '',
    submission_location TEXT DEFAULT '',
    contact_name TEXT DEFAULT '',
    contact_phone TEXT DEFAULT '',
    contact_email TEXT DEFAULT '',
    attachments_count INTEGER DEFAULT 0,
    attachments JSONB DEFAULT '[]'::jsonb,
    keywords_matched TEXT DEFAULT '',

    -- 采集元数据
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    scraped_by TEXT DEFAULT 'tender-scraper v3.2 fahcqmu',
    is_read INTEGER DEFAULT 0,

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 来源 URL (列表页路径)
    source_url TEXT DEFAULT '',

    -- 扩展字段 (cqggzy 没有但 fahcqmu 需要)
    org_unit TEXT DEFAULT '',           -- 信息数据处 / 总务处 / 其他 (从 URL 推断)
    contract_amount TEXT DEFAULT '',
    planned_publish_date TEXT DEFAULT '',
    tender_content TEXT DEFAULT '',
    project_no TEXT DEFAULT ''
);

-- 索引: URL 已自动唯一索引 (UNIQUE constraint)
CREATE INDEX IF NOT EXISTS idx_fahcqmu_url ON projects_fahcqmu USING btree (url) WHERE url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fahcqmu_publish_date ON projects_fahcqmu USING btree (publish_date DESC) WHERE publish_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fahcqmu_info_type ON projects_fahcqmu USING btree (info_type) WHERE info_type IS NOT NULL AND info_type <> '';
CREATE INDEX IF NOT EXISTS idx_fahcqmu_org_unit ON projects_fahcqmu USING btree (org_unit) WHERE org_unit IS NOT NULL AND org_unit <> '';
CREATE INDEX IF NOT EXISTS idx_fahcqmu_business_type ON projects_fahcqmu USING btree (business_type) WHERE business_type IS NOT NULL AND business_type <> '';

-- 注释
COMMENT ON TABLE projects_fahcqmu IS '重医附一院采购公告 (信息数据处 + 总务处 + 其他)';
COMMENT ON COLUMN projects_fahcqmu.url IS '详情页 URL (来自 gzb_cgxx_* 或 gw_yygg_zbgg_cgglczb2_*)';
COMMENT ON COLUMN projects_fahcqmu.info_type IS 'ygtjgg=阳光推介 / dygg=调研 / cggg=采购公告 / cgjggs=采购结果(信息处) / jggs=采购结果(总务处) / qt=其他';
COMMENT ON COLUMN projects_fahcqmu.org_unit IS '信息数据处 / 总务处 / 其他 (从 URL 路径推断)';
COMMENT ON COLUMN projects_fahcqmu.business_type IS '医院采购 (新枚举值)';

-- ============================================================================
-- 回滚 (手工):
--   DROP TABLE IF EXISTS projects_fahcqmu CASCADE;
-- ============================================================================
