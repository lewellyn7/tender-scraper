-- Migration: Add user_id to duplicate_records
-- Change: Add user_id column + composite unique constraint
-- Date: 2026-05-08

-- PostgreSQL
BEGIN;
ALTER TABLE duplicate_records ADD COLUMN IF NOT EXISTS user_id TEXT DEFAULT '';
DROP INDEX IF EXISTS idx_dup_canonical;
CREATE INDEX IF NOT EXISTS idx_dup_canonical ON duplicate_records(user_id, canonical_url);
COMMIT;

-- SQLite (run manually via sqlite3 CLI)
-- ALTER TABLE duplicate_records ADD COLUMN user_id TEXT DEFAULT '';
-- (SQLite requires table recreation to add a unique constraint)
