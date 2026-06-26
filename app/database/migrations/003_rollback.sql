-- Migration 003 Rollback: Remove updated_at trigger
-- ============================================================
-- 紧急回滚: 删除所有 trg_updated_at_* trigger 和 project_records.added updated_at 列
-- 不删除 set_updated_at() 函数 (可能被其他 trigger 引用)
-- ============================================================

DROP TRIGGER IF EXISTS trg_updated_at_project_records ON project_records;
DROP TRIGGER IF EXISTS trg_updated_at_projects ON projects;
DROP TRIGGER IF EXISTS trg_updated_at_projects_ccgp ON projects_ccgp;
DROP TRIGGER IF EXISTS trg_updated_at_projects_cqggzy ON projects_cqggzy;
DROP TRIGGER IF EXISTS trg_updated_at_projects_fahcqmu ON projects_fahcqmu;

-- 仅在 project_records 没有 updated_at 业务时, 移除列
-- ALTER TABLE project_records DROP COLUMN IF EXISTS updated_at;

DO $$
DECLARE
    trigger_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO trigger_count
    FROM information_schema.triggers
    WHERE trigger_name LIKE 'trg_updated_at_%';
    
    RAISE NOTICE '✅ 已删除 updated_at trigger, 剩余 % 个 (期望 0)', trigger_count;
END $$;