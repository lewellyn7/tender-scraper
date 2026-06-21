-- 001_create_bid_results.sql
-- 中标结果持久化表 (政府采购 + 工程招投标)
-- 创建: 2026-06-18, 任务: 中标排名分析 ETL

CREATE TABLE IF NOT EXISTS bid_results (
  id              BIGSERIAL PRIMARY KEY,
  source          TEXT NOT NULL DEFAULT 'cqggzy',
  project_id      INTEGER NOT NULL,
  url             TEXT NOT NULL,
  info_type       TEXT NOT NULL,
  category        TEXT NOT NULL,
  package_no      TEXT,
  winner_name     TEXT NOT NULL,
  winner_rank     INTEGER,
  bid_amount      TEXT,
  bid_amount_num  NUMERIC(18,2),
  winner_score    NUMERIC(6,2),
  publish_date    DATE NOT NULL,
  parsed_at       TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT uq_bid_source_proj UNIQUE (source, project_id, package_no, winner_name)
);

CREATE INDEX IF NOT EXISTS idx_bid_winner ON bid_results(winner_name);
CREATE INDEX IF NOT EXISTS idx_bid_date ON bid_results(publish_date);
CREATE INDEX IF NOT EXISTS idx_bid_cat_date ON bid_results(category, publish_date);
CREATE INDEX IF NOT EXISTS idx_bid_proj ON bid_results(project_id);