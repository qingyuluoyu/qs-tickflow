ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE users ADD COLUMN last_login_at REAL;

CREATE TABLE IF NOT EXISTS auth_attempts (
    attempt_key TEXT PRIMARY KEY,
    failure_count INTEGER NOT NULL DEFAULT 0,
    locked_until REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auth_attempts_locked_until ON auth_attempts(locked_until);
