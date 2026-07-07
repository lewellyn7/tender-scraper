-- Migration 007: favorites 表加 deadline 列
-- 引入: a8bf36c (T-3 截标提醒) 假设了 favorites.deadline 列存在, 但实际表没这列
-- 影响: notifications.py check_deadline_alerts 报 "column deadline does not exist", 功能静默失效
-- 修法: ALTER TABLE 加 deadline TEXT 列 (默认 '', 与项目级 deadline 字段类型一致)

ALTER TABLE favorites ADD COLUMN IF NOT EXISTS deadline TEXT DEFAULT '';

-- 索引: deadline 截标提醒按日期过滤
CREATE INDEX IF NOT EXISTS idx_favorites_deadline ON favorites (deadline)
WHERE deadline IS NOT NULL AND deadline != '';
