-- backfill_summaries.sql
-- 用法: docker exec -i tender-scraper-postgres psql -U root -d tender_scraper < scripts/backfill_summaries.sql
-- 描述: 用 title + info_type + budget + deadline + project_no 拼一个 100-500 字摘要
-- 排除: cp 已有值的 (避免覆盖)
-- 排除: 招标计划表 (title 本身就是摘要)
-- 实测: 18:13 UPDATE 81749 → cp_empty 93637 → 11888 (89.03%)

WITH src AS (
  SELECT
    p.id,
    p.title,
    COALESCE(NULLIF(p.info_type, ''), '招标公告') as info_type,
    NULLIF(p.budget, '') as budget,
    NULLIF(p.submission_deadline, '') as submission_deadline,
    NULLIF(p.project_no, '') as project_no,
    p.publish_date,
    TRIM(CONCAT_WS(E'\n',
      p.title,
      CONCAT('[', COALESCE(NULLIF(p.info_type, ''), '招标公告'), ']'),
      CASE WHEN p.budget IS NOT NULL AND p.budget != '' THEN CONCAT('预算: ', p.budget) END,
      CASE WHEN p.submission_deadline IS NOT NULL AND p.submission_deadline != '' THEN CONCAT('截止: ', p.submission_deadline) END,
      CASE WHEN p.project_no IS NOT NULL AND p.project_no != '' THEN CONCAT('项目编号: ', p.project_no) END
    )) as new_cp
  FROM projects_cqggzy p
  WHERE (p.content_preview IS NULL OR p.content_preview = '')
    AND p.title NOT LIKE '%招标计划表%'
)
UPDATE projects_cqggzy p
SET content_preview = LEFT(src.new_cp, 500)
FROM src
WHERE p.id = src.id;
