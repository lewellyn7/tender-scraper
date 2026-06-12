-- backfill_keywords_title.sql
-- 用法: docker exec -i tender-scraper-postgres psql -U root -d tender_scraper < scripts/backfill_keywords_title.sql
-- 描述: 从 projects_cqggzy.title 跑 keywords 表的 include/exclude 匹配, 填 keywords_matched
-- 注: 排除 '招标计划表' (AGENTS 6-10 教训: 招标计划表无 project_no, 关键词匹配仅用 title)
--     排除已有 keywords_matched (避免覆盖已匹配的)

WITH sub AS (
  SELECT
    p2.id,
    (SELECT string_agg(kw.keyword, ', ' ORDER BY kw.keyword)
     FROM keywords kw
     WHERE kw.category = 'include' AND kw.enabled = 1
       AND p2.title LIKE '%' || kw.keyword || '%'
    ) as matched_inc,
    EXISTS (SELECT 1 FROM keywords kw
            WHERE kw.category = 'exclude' AND kw.enabled = 1
              AND p2.title LIKE '%' || kw.keyword || '%'
           ) as has_exclude
  FROM projects_cqggzy p2
  WHERE p2.title NOT LIKE '%招标计划表%'  -- 招标计划表无 detail, 仅用 title 仍可匹配, 不排除
    AND (p2.keywords_matched IS NULL OR p2.keywords_matched = '')
)
UPDATE projects_cqggzy SET keywords_matched = sub.matched_inc
FROM sub
WHERE projects_cqggzy.id = sub.id AND COALESCE(sub.has_exclude, false) = false;
