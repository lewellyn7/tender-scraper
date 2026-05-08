-- Migration: Favorites user isolation
-- Change: UNIQUE(project_url) → UNIQUE(user_id, project_url)
-- Date: 2026-05-08

-- Step 1: Drop the old unique constraint (SQLite doesn't support IF EXISTS for constraint names,
-- so we recreate the table cleanly)

BEGIN;

-- Create new table with correct schema
CREATE TABLE IF NOT EXISTS favorites_new(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL DEFAULT '',
    project_url TEXT NOT NULL,
    title TEXT NOT NULL,
    source_url TEXT DEFAULT "",
    tender_type TEXT DEFAULT "",
    budget TEXT DEFAULT "",
    publish_date TEXT DEFAULT "",
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, project_url)
);

-- Copy data
INSERT INTO favorites_new SELECT * FROM favorites;

-- Drop old table
DROP TABLE favorites;

-- Rename new table
ALTER TABLE favorites_new RENAME TO favorites;

-- Recreate indexes (drop first if exists)
DROP INDEX IF EXISTS idx_favorites_user;
DROP INDEX IF EXISTS idx_favorites_url;
DROP INDEX IF EXISTS idx_favorites_title;
DROP INDEX IF EXISTS idx_favorites_updated;

CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id);
CREATE INDEX IF NOT EXISTS idx_favorites_url ON favorites(project_url);
CREATE INDEX IF NOT EXISTS idx_favorites_title ON favorites(title);
CREATE INDEX IF NOT EXISTS idx_favorites_updated ON favorites(updated_at);
CREATE INDEX IF NOT EXISTS idx_favorites_status ON favorites(status);

COMMIT;
