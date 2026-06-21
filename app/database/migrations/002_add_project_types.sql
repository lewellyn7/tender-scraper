-- 002_add_project_types.sql
-- 项目类型分类字段 (text[] 多标签)
-- 创建: 2026-06-20, 任务: 中标分析按类型分组
-- 依赖: 001_create_bid_results.sql + app/utils/bid_parser.classify_project_type + config/project_types.py

ALTER TABLE bid_results
  ADD COLUMN IF NOT EXISTS project_types TEXT[] NOT NULL DEFAULT ARRAY['其他'];

-- 索引: GIN 支持 project_types @> ARRAY['智能化'] 查询
CREATE INDEX IF NOT EXISTS idx_bid_project_types_gin
  ON bid_results USING GIN (project_types);

-- 索引: 单类型 (常规 btree 覆盖多数查询)
CREATE INDEX IF NOT EXISTS idx_bid_first_type
  ON bid_results ((project_types[1]))
  WHERE project_types IS NOT NULL;