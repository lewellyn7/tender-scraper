-- Migration 010: backfill scraped_at for existing projects_ccgp_intention_demand rows
--
-- 根因 (2026-07-21):
--   tender_to_db_row() (app/crawlers/ccgp_intent_demand.py) 返回的 dict 漏掉 scraped_at key,
--   导致 upsert_projects_ccgp_intention_demand (db.py:598) 在 INSERT 时显式写 NULL,
--   覆盖 DEFAULT CURRENT_TIMESTAMP. ON CONFLICT DO UPDATE 的
--   CASE WHEN EXCLUDED.scraped_at IS NOT NULL THEN ... ELSE table.scraped_at END
--   也保持原 NULL. 结果: 整表 scraped_at=NULL (1952 行).
--
-- 与 PR #80 commit 6551e3e fix(fahcqmu) 同类 bug, ccgp_intent_demand 当时漏修.
--
-- 修法:
--   1. 已修 crawler (加 "scraped_at": datetime.now().isoformat())
--   2. 本 migration backfill 已有 1952 行的 scraped_at
--      - 优先用 updated_at (反映数据最近被刷新时间, 最贴近"采集时间")
--      - 兜底 created_at, 最后 NOW()
--
-- 幂等: WHERE scraped_at IS NULL 限定, 重复执行 no-op.

BEGIN;

UPDATE projects_ccgp_intention_demand
SET scraped_at = COALESCE(updated_at, created_at, NOW())
WHERE scraped_at IS NULL;

-- 验证
-- SELECT COUNT(*) FILTER (WHERE scraped_at IS NULL) AS still_null,
--        COUNT(*) AS total,
--        MAX(scraped_at) AS max_scraped,
--        MIN(scraped_at) AS min_scraped
-- FROM projects_ccgp_intention_demand;

COMMIT;