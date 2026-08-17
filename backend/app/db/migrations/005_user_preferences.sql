CREATE TABLE IF NOT EXISTS user_preferences (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    value_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);
