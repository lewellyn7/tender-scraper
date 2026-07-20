-- 009_add_projects_unique_project_no.sql
-- 创建: 2026-07-21
-- 原因: projects 表 upsert_project() 用 ON CONFLICT (project_no) DO UPDATE,
--       但 projects.project_no 缺 UNIQUE 约束 → upsert_project 每次都失败,
--       导致 _sync_projects_link 把 fahcqmu/ccgp/cqggzy/cqyc 数据只写到了 _xxx 表,
--       联动到 projects 主表失败, 前端跨源查询看不到 7-19 之后的数据.
--
-- 验证: 86817 行无重复 project_no, 加 UNIQUE 不会冲突.
--
-- 用 UNIQUE INDEX (不用 CONSTRAINT) 因为:
--   1. UNIQUE INDEX 同样可作为 ON CONFLICT target (PG 9.5+)
--   2. CREATE UNIQUE INDEX IF NOT EXISTS 天然幂等
--   3. 现有 idx_projects_no 是非唯一索引, 不冲突, 但重复无意义, 保留避免破坏外部依赖
--
-- 副作用: 未来重复 project_no 的 INSERT 会失败 (这是正确行为)

CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_project_no
    ON projects (project_no);

-- 备注: NULL 在 UNIQUE 索引中允许多行, 符合 SQLite DDL 设计意图
--       (没有 project_no 的项目可以多条, 因为没有项目编号就无法去重)