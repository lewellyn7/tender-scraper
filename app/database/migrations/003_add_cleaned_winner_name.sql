-- 003_add_cleaned_winner_name.sql
-- 清洗后的中标单位名称 (2026-06-22 新增)
-- 背景: 采集时把整段公告内容（含企业资质/业绩/备注）当 winner_name
--       70%+ 记录 winner_name > 30 字且含冒号/资质/业绩
-- 清洗: 抽取第一个公司/机构名 (\S+有限公司|\S+有限责任公司|\S+股份公司|\S+厂|\S+中心)
-- 任务: analytics 排名按真实单位去重 + 工程招投标中标单位清洗
-- 依赖: 001_create_bid_results.sql

ALTER TABLE bid_results
  ADD COLUMN IF NOT EXISTS cleaned_winner_name TEXT;

-- 索引: 按清洗后单位查询 (排名统计)
CREATE INDEX IF NOT EXISTS idx_bid_cleaned_winner
  ON bid_results (cleaned_winner_name)
  WHERE cleaned_winner_name IS NOT NULL;
