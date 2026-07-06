-- ============================================================================
-- Migration 006: 重庆烟草采集 - 创建 projects_cqyc 表
-- ============================================================================
-- 创建时间：2026-07-06
-- 来源：重庆烟草网 https://www.966599.com/c/4/
--
-- 重庆烟草公司公开招标采购信息:
--   - 结果公示：成交结果公告、谈判结果公示、中标候选人公示、中选结果公示、结果公告、结果公示表
--   - 采购公告：采购公告、询价公告、采购邀请函、竞争性谈判公告、竞争谈判公告、公开招标公告
--   - 变更公告：变更公示、变更补遗、澄清补遗、澄清说明
--   - 流标：流标公示、流标公示表、流标公告
--   - 招租公告：招租公告、招租结果公示
--   预计全量：210 页 × 15 条 = ~3150 条
--
-- Schema 与 projects_fahcqmu 同构 (37 列), 额外加 info_type 字段区分 5 个分类.
-- URL 唯一约束，支持 ON CONFLICT (url) DO UPDATE 幂等写入.
-- ============================================================================

CREATE TABLE IF NOT EXISTS projects_cqyc (
    -- 主键
    id BIGSERIAL PRIMARY KEY,

    -- 唯一 URL (来自 966599.com 列表)
    url TEXT UNIQUE NOT NULL,

    -- 基础字段 (与 projects_fahcqmu 对齐)
    title TEXT NOT NULL DEFAULT '',
    category TEXT DEFAULT '',
    info_type TEXT DEFAULT '',          -- result_notice / purchase_notice / change_notice / failed_notice / rental_notice
    business_type TEXT DEFAULT '',      -- 烟草采购
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
    scraped_by TEXT DEFAULT 'tender-scraper v3.2 cqyc',
    is_read INTEGER DEFAULT 0,

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 来源 URL (列表页路径)
    source_url TEXT DEFAULT '',

    -- 扩展字段
    project_no TEXT DEFAULT ''
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_cqyc_url ON projects_cqyc USING btree (url) WHERE url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cqyc_publish_date ON projects_cqyc USING btree (publish_date DESC) WHERE publish_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cqyc_info_type ON projects_cqyc USING btree (info_type) WHERE info_type IS NOT NULL AND info_type <> '';
CREATE INDEX IF NOT EXISTS idx_cqyc_business_type ON projects_cqyc USING btree (business_type) WHERE business_type IS NOT NULL AND business_type <> '';

-- 注释
COMMENT ON TABLE projects_cqyc IS '重庆烟草采购公告 (5 分类：结果公示/采购公告/变更公告/流标/招租)';
COMMENT ON COLUMN projects_cqyc.url IS '详情页 URL (/a/YYYYMMDD/{uuid}.html)';
COMMENT ON COLUMN projects_cqyc.info_type IS 'result_notice=结果公示 / purchase_notice=采购公告 / change_notice=变更公告 / failed_notice=流标 / rental_notice=招租';
COMMENT ON COLUMN projects_cqyc.business_type IS '烟草采购 (新枚举值)';

-- ============================================================================
-- 回滚 (手工):
--   DROP TABLE IF EXISTS projects_cqyc CASCADE;
-- ============================================================================