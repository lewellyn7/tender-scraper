-- backfill_info_type_publish_date.sql
-- 用法: docker exec -i tender-scraper-postgres psql -U root -d tender_scraper < scripts/backfill_info_type_publish_date.sql
-- 描述: 3 步批量回填
--   1. info_type 通过 URL 模式 (categoryNum 9 位) 推理
--   2. publish_date 从 full_content 提取中文日期 (YYYY年M月D日) 或 ISO (YYYY-MM-DD)
--   3. publish_date 从列表页 URL /YYYYMMDD/ 路径提取 (详情页 URL 没日期, 跳过)
-- 实测 (18:55):
--   info_type: 235 → 0
--   publish_date: 235 → 164 (剩 144 fc 无日期 + 20 fc_empty, 需 fetch 详情回填)
-- 排除: 已有值的 (避免覆盖)

-- Part 1: info_type 通过 URL 模式
WITH url_type AS (
  SELECT id,
    CASE 
      WHEN url LIKE '%014005001%' THEN '采购公告'
      WHEN url LIKE '%014005002%' THEN '变更公告'
      WHEN url LIKE '%014005004%' THEN '采购结果公告'
      WHEN url LIKE '%014005008%' THEN '单一来源公示'
      WHEN url LIKE '%014001001%' THEN '招标公告'
      WHEN url LIKE '%014001002%' THEN '答疑补遗'
      WHEN url LIKE '%014001003%' THEN '中标候选人公示'
      WHEN url LIKE '%014001004%' THEN '中标结果公示'
      WHEN url LIKE '%014001019%' THEN '招标计划'
      WHEN url LIKE '%014001020%' THEN '终止公告'
      WHEN url LIKE '%014001021%' THEN '终止公告'
      WHEN url LIKE '%014001014%' THEN '邀标信息'
    END as new_it
  FROM projects_cqggzy
  WHERE info_type IS NULL OR info_type = ''
)
UPDATE projects_cqggzy p
SET info_type = url_type.new_it
FROM url_type
WHERE p.id = url_type.id AND url_type.new_it IS NOT NULL;

-- Part 2: publish_date 从 full_content 提取 (中文 / ISO 两种格式)
WITH pd_extract AS (
  SELECT id,
    CASE
      WHEN full_content ~ '20[0-9]{2}年[0-9]{1,2}月[0-9]{1,2}日' THEN
        TO_DATE(
          SUBSTRING(full_content FROM '20[0-9]{2}年[0-9]{1,2}月[0-9]{1,2}日'),
          'YYYY"年"MM"月"DD"日"'
        )
      WHEN full_content ~ '20[0-9]{2}-[0-9]{1,2}-[0-9]{1,2}' THEN
        TO_DATE(
          SUBSTRING(full_content FROM '20[0-9]{2}-[0-9]{1,2}-[0-9]{1,2}'),
          'YYYY-MM-DD'
        )
    END as new_pd
  FROM projects_cqggzy
  WHERE publish_date IS NULL
    AND full_content IS NOT NULL AND full_content != ''
    AND (full_content ~ '20[0-9]{2}年[0-9]{1,2}月[0-9]{1,2}日' 
         OR full_content ~ '20[0-9]{2}-[0-9]{1,2}-[0-9]{1,2}')
)
UPDATE projects_cqggzy p
SET publish_date = pd_extract.new_pd
FROM pd_extract
WHERE p.id = pd_extract.id AND pd_extract.new_pd IS NOT NULL;

-- Part 3: publish_date 从列表页 URL /YYYYMMDD/ 路径提取
-- (旧版 CQGGZY 列表页 URL 形如 /xxhz/infoSearch/.../20251124/...)
WITH date_extract AS (
  SELECT id,
    TO_DATE(
      COALESCE(
        SUBSTRING(url FROM '/20[0-9]{6}/'),
        SUBSTRING(url FROM '/19[0-9]{6}/')
      ),
      'YYYYMMDD'
    ) as new_pd
  FROM projects_cqggzy
  WHERE publish_date IS NULL
    AND (url ~ '/20[0-9]{6}/' OR url ~ '/19[0-9]{6}/')
)
UPDATE projects_cqggzy p
SET publish_date = date_extract.new_pd
FROM date_extract
WHERE p.id = date_extract.id AND date_extract.new_pd IS NOT NULL;
