-- Migration 012: backfill projects_ccgp_intention_demand.budget 单位换算
--
-- 根因 (2026-07-21):
--   PR #82 加了 parse_intent_demand_json() 的 budget 元→万元启发式换算
--   (money > 10000 视为元, 除以 10000). 但 PR #82 之前采集的 1952 行
--   budget 已经是错的格式: "1320000.00万元" (raw 元 + 万元 后缀) 应是 "132.00万元".
--
-- 影响: 134 行 budget 字段是 raw 元 + 万元, 显示为 "X百万万元" 这种荒谬数字.
--
-- 修法:
--   1. 已修 crawler (PR #82) — 后续采集走新 parser
--   2. 本 migration backfill 老的 budget_overflow 行
--
-- 启发式 (与 parser 一致):
--   budget 匹配 ^[0-9]{5,}\.?[0-9]*万元$ → 数字部分 > 10000 → 除 10000 → 重新格式化为 X.XX万元
--   数字 ≤ 10000 → 保持原样 (防御: 避免误转)
--
-- 幂等: 用 budget 字段过滤, 已转换过的 (NNNNN.XX万元, N < 10000) 不在匹配范围

BEGIN;

WITH parsed AS (
    SELECT id,
           (regexp_match(budget, '^([0-9]+\.?[0-9]*)万元$'))[1] AS num_str
    FROM projects_ccgp_intention_demand
    WHERE budget ~ '^[0-9]{5,}\.?[0-9]*万元$'
)
UPDATE projects_ccgp_intention_demand t
SET budget = TO_CHAR((parsed.num_str)::numeric / 10000, 'FM999990.00') || '万元'
FROM parsed
WHERE t.id = parsed.id
  AND (parsed.num_str)::numeric > 10000;

-- 验证
-- SELECT
--   COUNT(*) FILTER (WHERE budget ~ '^[0-9]{5,}\.?[0-9]*万元\$') AS still_overflow,
--   COUNT(*) FILTER (WHERE budget ~ '^[0-9]+\.?[0-9]*万元\$' AND budget !~ '^[0-9]{5,}') AS normal,
--   COUNT(*) AS total
-- FROM projects_ccgp_intention_demand;

COMMIT;

-- 附: deadline 字段不回填
--   原因: 旧代码没捕获 endTime, DB 里没有源数据. PR #83 (本 PR) 修
--   crawler + upsert cols 后, 下次 re-collect 用 days=180 捕获尽可能多的历史数据.
--   完全覆盖需要 API 历史数据仍可访问 (实测 7-02 之前的数据 API 已 404, 无法回填).