-- Migration 008: 回填 projects_cqyc 表 info_type='other' 的 9 条
-- 引入: classify_by_title 漏匹配 6 个 keyword, 导致 9 条入 other
-- 修法: 已 hot-deploy 修复 cqyc.py; 此 SQL 回填历史 9 条

BEGIN;

-- 1. backup (审计)
CREATE TEMP TABLE _cqyc_other_backfill_log AS
SELECT id, title, info_type, NOW() as backfill_at
FROM projects_cqyc
WHERE info_type='other' AND (
  title LIKE '%成交结果公示%'
  OR title LIKE '%中标候选人公示表%'
  OR title LIKE '%中选人确认公示表%'
  OR title LIKE '%直接采购邀请%'
  OR title LIKE '%变更公告%'
  OR title LIKE '%暂停招投标活动的公告%'
);

-- 2. result_notice (6 条)
UPDATE projects_cqyc SET info_type='result_notice' WHERE info_type='other' AND (
  title LIKE '%成交结果公示%' OR title LIKE '%中标候选人公示表%' OR title LIKE '%中选人确认公示表%'
);

-- 3. purchase_notice (1 条)
UPDATE projects_cqyc SET info_type='purchase_notice' WHERE info_type='other' AND title LIKE '%直接采购邀请%';

-- 4. change_notice (2 条)
UPDATE projects_cqyc SET info_type='change_notice' WHERE info_type='other' AND (
  title LIKE '%变更公告%' OR title LIKE '%暂停招投标活动的公告%'
);

COMMIT;

-- 验证: SELECT info_type, COUNT(*) FROM projects_cqyc GROUP BY 1 ORDER BY 2 DESC;
