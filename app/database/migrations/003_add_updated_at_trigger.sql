-- Migration 003: Add updated_at trigger to projects_* tables
-- ============================================================
-- 目的: 让 UPDATE 时自动更新 updated_at = NOW(), 便于 debug + 审计
-- 设计: 单一函数 set_updated_at() + 每张表 1 个 trigger
-- 幂等: 全部用 IF NOT EXISTS / OR REPLACE, 可重入
-- 回滚: 见 003_rollback.sql
-- 应用日期: 2026-06-27
-- 作者: lewellyn + 贾维斯
-- ============================================================

-- 1. 触发器函数 (全局共享)
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 2. project_records: 先加 updated_at 列, 再加 trigger
-- ============================================================
ALTER TABLE project_records ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

DROP TRIGGER IF EXISTS trg_updated_at_project_records ON project_records;
CREATE TRIGGER trg_updated_at_project_records
BEFORE UPDATE ON project_records
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- 3. projects
-- ============================================================
DROP TRIGGER IF EXISTS trg_updated_at_projects ON projects;
CREATE TRIGGER trg_updated_at_projects
BEFORE UPDATE ON projects
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- 4. projects_ccgp
-- ============================================================
DROP TRIGGER IF EXISTS trg_updated_at_projects_ccgp ON projects_ccgp;
CREATE TRIGGER trg_updated_at_projects_ccgp
BEFORE UPDATE ON projects_ccgp
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- 5. projects_cqggzy
-- ============================================================
DROP TRIGGER IF EXISTS trg_updated_at_projects_cqggzy ON projects_cqggzy;
CREATE TRIGGER trg_updated_at_projects_cqggzy
BEFORE UPDATE ON projects_cqggzy
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- 6. projects_fahcqmu
-- ============================================================
DROP TRIGGER IF EXISTS trg_updated_at_projects_fahcqmu ON projects_fahcqmu;
CREATE TRIGGER trg_updated_at_projects_fahcqmu
BEFORE UPDATE ON projects_fahcqmu
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- 验证 (应用后自动 SELECT 检查)
-- ============================================================
DO $$
DECLARE
    trigger_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO trigger_count
    FROM information_schema.triggers
    WHERE trigger_name LIKE 'trg_updated_at_%';
    
    RAISE NOTICE '✅ 已创建 % 个 updated_at trigger (期望 5)', trigger_count;
    
    IF trigger_count != 5 THEN
        RAISE EXCEPTION '❌ trigger 数量不匹配, 应用失败';
    END IF;
END $$;