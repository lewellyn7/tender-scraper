-- Migration 011: backfill projects_ccgp_intention_demand.url 到正确的 stock-resources-front 格式
--
-- 根因 (2026-07-21):
--   build_doc_url() (app/crawlers/ccgp_intent_demand.py:121) 旧版本合成 URL 用
--     /intention-view/{id}    (type=2 采购意向)
--     /demand-view/{id}       (type=1 需求调查)
--   实测: 这两个路径现已 404, 前端页面真实 URL 是
--     /stock-resources-front/intentionView?id={id}    (type=2)
--     /stock-resources-front/demandView?id={id}       (type=1)
--
-- 影响: 已有 1952 行 url 字段指向 404 链接, 用户点击无法打开
--
-- 修法:
--   1. 已修 crawler (build_doc_url 改用 stock-resources-front 格式) — 后续采集用新 URL
--   2. 本 migration backfill 已存在的 1952 行 url 字段
--
-- 幂等: 用 REPLACE 精确匹配旧 URL 格式, 重复执行 no-op

BEGIN;

-- type=2 (采购意向): /intention-view/{id} → /stock-resources-front/intentionView?id={id}
UPDATE projects_ccgp_intention_demand
SET url = REPLACE(
    url,
    '/intention-view/',
    '/stock-resources-front/intentionView?id='
)
WHERE url LIKE '%/intention-view/%';

-- type=1 (需求调查): /demand-view/{id} → /stock-resources-front/demandView?id={id}
UPDATE projects_ccgp_intention_demand
SET url = REPLACE(
    url,
    '/demand-view/',
    '/stock-resources-front/demandView?id='
)
WHERE url LIKE '%/demand-view/%';

-- 验证
-- SELECT
--   COUNT(*) FILTER (WHERE url LIKE '%/stock-resources-front/%') AS new_format,
--   COUNT(*) FILTER (WHERE url LIKE '%/intention-view/%' OR url LIKE '%/demand-view/%') AS old_format,
--   COUNT(*) AS total
-- FROM projects_ccgp_intention_demand;

COMMIT;

-- 附: deadline 字段 (预计采购时间) 不在本 migration 处理
--   原因: 旧代码没捕获 endTime, DB 里没有源数据可 backfill
--   解决: PR #82 (本 PR) 修 crawler 后, 下次 cron 跑会重新采集, deadline 自动填
--         旧的 1952 行 deadline 保持 NULL (6h 内新 cron 全覆盖)