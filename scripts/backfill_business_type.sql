-- backfill_business_type.sql
-- 用法: docker exec -i tender-scraper-postgres psql -U root -d tender_scraper < scripts/backfill_business_type.sql
-- 描述: 用 URL 模式推业务大类, 填补 NULL
-- 实测: 18:13 UPDATE 400 (014005→政府采购 207, 014001→工程招投标 193)
-- 排除: business_type 已有值的 (避免覆盖)

-- 政府采购: /trade/014005
UPDATE projects_cqggzy
SET business_type = '政府采购'
WHERE (business_type IS NULL OR business_type = '')
  AND url LIKE '%014005%';

-- 工程招投标: /trade/014001
UPDATE projects_cqggzy
SET business_type = '工程招投标'
WHERE (business_type IS NULL OR business_type = '')
  AND url LIKE '%014001%';
