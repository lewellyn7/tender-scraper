-- ============================================================================
-- Migration 004: CCGP 采购意向 / 需求调查 采集 - 创建 projects_ccgp_intention_demand 表
-- ============================================================================
-- 创建时间: 2026-07-01
-- 来源: feat/ccgp-intention-demand-2026-07-01
--
-- 重庆市政府采购网 (https://www.ccgp-chongqing.gov.cn) 新版接口:
--   - 采购意向: /yw-gateway/demand/demand/front?type=2 (当前 ~33K 条)
--   - 需求调查: /yw-gateway/demand/demand/front?type=1 (当前 ~4K 条)
-- 合计首次全量: ~37K 条; 30 天增量预期 ~几百条
--
-- 字段与 projects_fahcqmu / projects_ccgp 同构 (38 列), URL 唯一约束 + ON CONFLICT 幂等写入.
-- info_type 取值: '采购意向' (type=2) / '需求调查' (type=1)
-- business_type / category 固定为 '政府采购' (与前端 6 月分类标准一致)
-- ============================================================================

CREATE TABLE IF NOT EXISTS projects_ccgp_intention_demand (
    -- 主键
    id BIGSERIAL PRIMARY KEY,

    -- 唯一 URL (合成: https://www.ccgp-chongqing.gov.cn/intention-view/{id} | demand-view/{id})
    url TEXT UNIQUE NOT NULL,

    -- 基础字段
    title TEXT NOT NULL DEFAULT '',
    category TEXT DEFAULT '',                -- 固定 '政府采购'
    info_type TEXT DEFAULT '',               -- 采购意向 / 需求调查
    business_type TEXT DEFAULT '',           -- 固定 '政府采购'
    publish_date DATE,
    publish_date_raw TEXT DEFAULT '',
    content_preview TEXT DEFAULT '',
    full_content TEXT DEFAULT '',
    budget TEXT DEFAULT '',                  -- money 字段
    bid_amount TEXT DEFAULT '',
    deadline TIMESTAMP,
    opening_date TIMESTAMP,
    region TEXT DEFAULT '',                  -- createRegionName
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
    attachments JSONB DEFAULT '[]'::jsonb,   -- 仅存路径, 不下载
    keywords_matched TEXT DEFAULT '',

    -- 采集元数据
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    scraped_by TEXT DEFAULT 'tender-scraper v3.2 ccgp_intent_demand',
    is_read INTEGER DEFAULT 0,

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 来源 URL (列表页)
    source_url TEXT DEFAULT '',

    -- 扩展字段
    contract_amount TEXT DEFAULT '',
    planned_publish_date TEXT DEFAULT '',
    tender_content TEXT DEFAULT '',          -- intentionDetaileList 拼接
    project_no TEXT DEFAULT '',

    -- 源数据字段 (供前端按需下载附件/回溯)
    source_id TEXT DEFAULT '',               -- API 返回的 id 数字
    source_type SMALLINT DEFAULT 0           -- 1=需求调查 2=采购意向 (与 API type 一致)
);

-- 索引
CREATE UNIQUE INDEX IF NOT EXISTS idx_ccgp_id_url
    ON projects_ccgp_intention_demand USING btree (url) WHERE url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ccgp_id_publish_date
    ON projects_ccgp_intention_demand USING btree (publish_date DESC) WHERE publish_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ccgp_id_info_type
    ON projects_ccgp_intention_demand USING btree (info_type) WHERE info_type IS NOT NULL AND info_type <> '';
CREATE INDEX IF NOT EXISTS idx_ccgp_id_business_type
    ON projects_ccgp_intention_demand USING btree (business_type) WHERE business_type IS NOT NULL AND business_type <> '';
CREATE INDEX IF NOT EXISTS idx_ccgp_id_source_type
    ON projects_ccgp_intention_demand USING btree (source_type) WHERE source_type IS NOT NULL AND source_type <> 0;
CREATE INDEX IF NOT EXISTS idx_ccgp_id_scraped_at
    ON projects_ccgp_intention_demand USING btree (scraped_at DESC) WHERE scraped_at IS NOT NULL;

-- updated_at 自动触发器 (复用 migration 003 的 set_updated_at() 函数)
DROP TRIGGER IF EXISTS trg_updated_at_projects_ccgp_intention_demand ON projects_ccgp_intention_demand;
CREATE TRIGGER trg_updated_at_projects_ccgp_intention_demand
BEFORE UPDATE ON projects_ccgp_intention_demand
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 注释
COMMENT ON TABLE projects_ccgp_intention_demand IS 'CCGP 采购意向 + 需求调查 (type=2 / type=1) 政府采购';
COMMENT ON COLUMN projects_ccgp_intention_demand.url IS '合成 URL: /intention-view/{id} (type=2) | /demand-view/{id} (type=1)';
COMMENT ON COLUMN projects_ccgp_intention_demand.info_type IS '采购意向 (type=2) / 需求调查 (type=1)';
COMMENT ON COLUMN projects_ccgp_intention_demand.business_type IS '固定: 政府采购';
COMMENT ON COLUMN projects_ccgp_intention_demand.category IS '固定: 政府采购';
COMMENT ON COLUMN projects_ccgp_intention_demand.attachments IS 'JSONB: [{fileName,filePath,contentType,size,time}] - 仅存路径, 按需下载';
COMMENT ON COLUMN projects_ccgp_intention_demand.tender_content IS 'intentionDetaileList[].title+content 拼接';
COMMENT ON COLUMN projects_ccgp_intention_demand.source_id IS 'API 返回的 id 数字 (供 /api/ccgp-intent-demand/annex/{id} 查附件)';
COMMENT ON COLUMN projects_ccgp_intention_demand.source_type IS 'API type: 1=需求调查 2=采购意向';

-- ============================================================================
-- 回滚 (手工):
--   DROP TABLE IF EXISTS projects_ccgp_intention_demand CASCADE;
-- ============================================================================
