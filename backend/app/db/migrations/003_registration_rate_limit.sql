CREATE TABLE IF NOT EXISTS registration_attempts (
    attempt_key TEXT PRIMARY KEY,
    window_started_at REAL NOT NULL,
    success_count INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_registration_attempts_updated_at
ON registration_attempts(updated_at);
