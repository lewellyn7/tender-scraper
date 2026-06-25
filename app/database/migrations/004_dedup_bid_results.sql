-- ============================================================================
-- 004_dedup_bid_results.sql
--
-- 目的: 修复 bid_results 表 66.5% 重复数据的 bug
-- 时机: 2026-06-25
--
-- 根因:
--   唯一约束 uq_bid_source_proj 用的是 winner_name (未清洗, 含附注文本),
--   而非 cleaned_winner_name (清洗后). 每条 record 附注不同 →
--   同一 (project_id, package_no, 中标人) 被多次插入 (高达 26 次).
--
-- 影响:
--   5,997 行 → 2,015 行 (3,982 行重复)
--   analysis/bid-rank 排名虚高 2-26 倍
--
-- 修复:
--   1) DELETE 重复行 (保留最早 1 条, 按 id 升序)
--   2) DROP 旧唯一约束
--   3) ADD 新唯一约束 (用 cleaned_winner_name 替代 winner_name)
--
-- 安全:
--   - cleaned_winner_name IS NULL 的 123 行不动 (信息不完整, 保留备查)
--   - 不改应用代码 (DB 层唯一约束足够)
-- ============================================================================

BEGIN;

-- ─── Step 1: 统计预览 (不删除, 仅输出) ─────────────────────────────────────
DO $$
DECLARE
    total_rows INT;
    uniq_rows INT;
    dup_rows INT;
BEGIN
    SELECT count(*) INTO total_rows
    FROM bid_results WHERE cleaned_winner_name IS NOT NULL;

    SELECT count(*) INTO uniq_rows FROM (
        SELECT DISTINCT source, project_id, package_no, cleaned_winner_name
        FROM bid_results
        WHERE cleaned_winner_name IS NOT NULL
    ) t;

    dup_rows := total_rows - uniq_rows;
    RAISE NOTICE 'Before: total=%, unique=%, duplicates=%', total_rows, uniq_rows, dup_rows;
END $$;

-- ─── Step 2: 删除重复行 (保留每组最早 1 条) ────────────────────────────────
DELETE FROM bid_results
WHERE id IN (
    SELECT id FROM (
        SELECT id,
               ROW_NUMBER() OVER (
                   PARTITION BY source, project_id, package_no, cleaned_winner_name
                   ORDER BY id
               ) AS rn
        FROM bid_results
        WHERE cleaned_winner_name IS NOT NULL
    ) t
    WHERE rn > 1
);

-- ─── Step 3: 验证删除结果 ──────────────────────────────────────────────────
DO $$
DECLARE
    after_total INT;
    after_uniq INT;
BEGIN
    SELECT count(*) INTO after_total
    FROM bid_results WHERE cleaned_winner_name IS NOT NULL;

    SELECT count(*) INTO after_uniq FROM (
        SELECT DISTINCT source, project_id, package_no, cleaned_winner_name
        FROM bid_results
        WHERE cleaned_winner_name IS NOT NULL
    ) t;

    RAISE NOTICE 'After:  total=%, unique=%', after_total, after_uniq;

    IF after_total != after_uniq THEN
        RAISE EXCEPTION 'Dedup failed: total=% != unique=%', after_total, after_uniq;
    END IF;
END $$;

-- ─── Step 4: 替换唯一约束 (winner_name → cleaned_winner_name) ──────────────
ALTER TABLE bid_results DROP CONSTRAINT IF EXISTS uq_bid_source_proj;

ALTER TABLE bid_results
    ADD CONSTRAINT uq_bid_source_proj_cleaned
    UNIQUE (source, project_id, package_no, cleaned_winner_name);

-- ─── Step 5: 最终检查 ──────────────────────────────────────────────────────
DO $$
DECLARE
    null_count INT;
    total_count INT;
BEGIN
    SELECT count(*) INTO null_count FROM bid_results WHERE cleaned_winner_name IS NULL;
    SELECT count(*) INTO total_count FROM bid_results;

    RAISE NOTICE 'Final: total=%, with_cleaned_winner=%, without_cleaned_winner=%',
        total_count, total_count - null_count, null_count;
END $$;

COMMIT;
