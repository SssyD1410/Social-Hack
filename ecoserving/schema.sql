-- EcoServing database schema (SQLite)

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS rate_events;
DROP TABLE IF EXISTS reports;
DROP TABLE IF EXISTS messages;
DROP TABLE IF EXISTS conversations;
DROP TABLE IF EXISTS volunteer_signups;
DROP TABLE IF EXISTS volunteer_requests;
DROP TABLE IF EXISTS food_requests;
DROP TABLE IF EXISTS food_offers;
DROP TABLE IF EXISTS verification_documents;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    email               TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash       TEXT    NOT NULL,
    name                TEXT    NOT NULL,
    role                TEXT    NOT NULL CHECK (role IN ('supplier', 'distributor', 'volunteer', 'consumer', 'admin')),
    org_name            TEXT,
    phone               TEXT,
    city                TEXT,
    address             TEXT,
    bio                 TEXT,
    lat                 REAL,
    lng                 REAL,
    -- Distributors must be verified before they can claim food or post requests.
    registration_number TEXT,
    verification_status TEXT    NOT NULL DEFAULT 'not_required'
                        CHECK (verification_status IN ('not_required', 'unverified', 'pending', 'verified', 'rejected')),
    verification_note   TEXT,
    -- Set by an admin (e.g. after a confirmed scam report); suspended accounts can't log in.
    suspended_at        TEXT,
    suspended_reason    TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE verification_documents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    doc_type      TEXT    NOT NULL,
    stored_name   TEXT    NOT NULL,
    original_name TEXT    NOT NULL,
    uploaded_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE food_offers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title               TEXT    NOT NULL,
    description         TEXT    NOT NULL,
    food_type           TEXT    NOT NULL,
    dietary_tags        TEXT,
    quantity            TEXT    NOT NULL,
    size                TEXT    NOT NULL DEFAULT 'medium' CHECK (size IN ('small', 'medium', 'large')),
    location            TEXT    NOT NULL,
    city                TEXT,
    lat                 REAL,
    lng                 REAL,
    photo               TEXT,
    pickup_start        TEXT,
    pickup_deadline     TEXT    NOT NULL,
    visible_distributors INTEGER NOT NULL DEFAULT 1,
    visible_volunteers  INTEGER NOT NULL DEFAULT 0,
    visible_consumers   INTEGER NOT NULL DEFAULT 0,
    status              TEXT    NOT NULL DEFAULT 'available'
                        CHECK (status IN ('available', 'claimed', 'completed', 'cancelled')),
    claimed_by          INTEGER REFERENCES users(id) ON DELETE SET NULL,
    claimed_at          TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE food_requests (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    distributor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title          TEXT    NOT NULL,
    description    TEXT    NOT NULL,
    quantity       TEXT    NOT NULL,
    location       TEXT    NOT NULL,
    city           TEXT,
    lat            REAL,
    lng            REAL,
    photo          TEXT,
    needed_by      TEXT    NOT NULL,
    status         TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'pledged', 'fulfilled', 'closed')),
    pledged_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE volunteer_requests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    poster_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title        TEXT    NOT NULL,
    tasks        TEXT    NOT NULL,
    requirements TEXT,
    location     TEXT    NOT NULL,
    city         TEXT,
    lat          REAL,
    lng          REAL,
    photo        TEXT,
    start_time   TEXT    NOT NULL,
    end_time     TEXT    NOT NULL,
    slots        INTEGER NOT NULL DEFAULT 1 CHECK (slots > 0),
    status       TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'filled', 'closed')),
    created_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE volunteer_signups (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id   INTEGER NOT NULL REFERENCES volunteer_requests(id) ON DELETE CASCADE,
    volunteer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message      TEXT,
    status       TEXT    NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'declined', 'withdrawn')),
    created_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (request_id, volunteer_id)
);

-- One conversation per pair of users (user_low < user_high).
CREATE TABLE conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_low   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_high  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (user_low, user_high),
    CHECK (user_low < user_high)
);

CREATE TABLE messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sender_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body            TEXT    NOT NULL,
    -- Optional link to the post the message is about ('offer', 'food_request', 'volunteer_request').
    ref_type        TEXT,
    ref_id          INTEGER,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    read_at         TEXT
);

CREATE INDEX idx_offers_status ON food_offers(status, pickup_deadline);
CREATE INDEX idx_food_requests_status ON food_requests(status);
CREATE INDEX idx_vol_requests_status ON volunteer_requests(status);
CREATE INDEX idx_messages_conv ON messages(conversation_id, id);
