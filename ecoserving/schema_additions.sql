-- Tables added after the first release. Safe to run on every start (IF NOT EXISTS).

-- Scam / fraud / abuse reports from users, reviewed by admins.
CREATE TABLE IF NOT EXISTS reports (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reported_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    -- What was reported: 'offer', 'food_request', 'volunteer_request' or 'user'.
    target_type      TEXT    NOT NULL CHECK (target_type IN ('offer', 'food_request', 'volunteer_request', 'user')),
    target_id        INTEGER NOT NULL,
    category         TEXT    NOT NULL,
    details          TEXT    NOT NULL,
    status           TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'reviewing', 'resolved', 'dismissed')),
    admin_note       TEXT,
    handled_by       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    handled_at       TEXT,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, created_at);

-- Recent attempts per key (e.g. "login:ip:1.2.3.4"), for rate limiting.
CREATE TABLE IF NOT EXISTS rate_events (
    key TEXT NOT NULL,
    at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rate_events ON rate_events(key, at);
