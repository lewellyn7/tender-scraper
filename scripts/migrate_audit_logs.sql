-- Migration: add audit_logs table for PostgreSQL
-- Run this manually if using PostgreSQL (ENV: DATABASE_URL starts with postgresql://)

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    event VARCHAR(50) NOT NULL,
    user_id VARCHAR(100),
    ip_address VARCHAR(45),
    user_agent TEXT,
    resource VARCHAR(500),
    result VARCHAR(20),
    details JSONB DEFAULT '{}',
    timestamp TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_logs(event);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp);
