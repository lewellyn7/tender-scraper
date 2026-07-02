-- Migration 005: Delta Sync 索引 (DataCache v4)
-- ============================================================
-- 目的: 让 delta_load_since(ts) 走索引扫描, 不全表 seq scan
-- 设计: 3 张表各加 1 个 btree 索引 on updated_at
--       部分索引: WHERE updated_at IS NOT NULL (绝大多数场景)
-- 幂等: IF NOT EXISTS, 可重入
-- 回滚: DROP INDEX (手动)
-- 应用日期: 2026-06-29
-- 作者: lewellyn + 贾维斯
-- ============================================================

-- 1. projects_cqggzy
CREATE INDEX IF NOT EXISTS idx_cqggzy_updated_at 
    ON projects_cqggzy (updated_at) 
    WHERE updated_at IS NOT NULL;

-- 2. projects_ccgp
CREATE INDEX IF NOT EXISTS idx_ccgp_updated_at 
    ON projects_ccgp (updated_at) 
    WHERE updated_at IS NOT NULL;

-- 3. projects_fahcqmu
CREATE INDEX IF NOT EXISTS idx_fahcqmu_updated_at 
    ON projects_fahcqmu (updated_at) 
    WHERE updated_at IS NOT NULL;

-- ============================================================
-- 验证
-- ============================================================
DO $$
DECLARE
    idx_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO idx_count
    FROM pg_indexes
    WHERE indexname IN (
        'idx_cqggzy_updated_at',
        'idx_ccgp_updated_at',
        'idx_fahcqmu_updated_at'
    );
    
    RAISE NOTICE '✅ 已创建 % 个 updated_at 索引 (期望 3)', idx_count;
    
    IF idx_count != 3 THEN
        RAISE EXCEPTION '❌ 索引数量不匹配, 应用失败';
    END IF;
END $$;