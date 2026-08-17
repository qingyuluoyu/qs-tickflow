CREATE TABLE IF NOT EXISTS user_ai_profiles (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    base_url TEXT NOT NULL,
    model TEXT NOT NULL,
    encrypted_api_key BLOB,
    user_agent TEXT NOT NULL DEFAULT '',
    codex_command TEXT NOT NULL DEFAULT '',
    codex_reasoning_effort TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);
