"""J.A.R.V.I.S DB schema — plain SQL for aiosqlite (no ORM)."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_usage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device      TEXT    NOT NULL DEFAULT 'mobile',
    package     TEXT    NOT NULL,
    app_name    TEXT,
    started_at  TEXT    NOT NULL,
    ended_at    TEXT,
    duration_s  INTEGER,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pc_activity (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    window_title TEXT    NOT NULL,
    process_name TEXT,
    url          TEXT,
    started_at   TEXT    NOT NULL,
    ended_at     TEXT,
    duration_s   INTEGER,
    idle         INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transcripts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT    NOT NULL DEFAULT 'mic',
    audio_path  TEXT,
    text        TEXT    NOT NULL,
    summary     TEXT,
    language    TEXT    NOT NULL DEFAULT 'ko',
    duration_s  REAL,
    recorded_at TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS promises (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    transcript_id INTEGER REFERENCES transcripts(id),
    content       TEXT    NOT NULL,
    assignee      TEXT,
    due_date      TEXT,
    status        TEXT    NOT NULL DEFAULT 'pending',
    reminded      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS email_tracking (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_id    TEXT    NOT NULL UNIQUE,
    subject     TEXT    NOT NULL,
    sender      TEXT    NOT NULL,
    received_at TEXT    NOT NULL,
    replied     INTEGER NOT NULL DEFAULT 0,
    replied_at  TEXT,
    priority    TEXT    NOT NULL DEFAULT 'normal',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS calendar_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    google_event_id TEXT    UNIQUE,
    title           TEXT    NOT NULL,
    description     TEXT,
    start_time      TEXT    NOT NULL,
    end_time        TEXT,
    location        TEXT,
    attendees       TEXT,
    status          TEXT    NOT NULL DEFAULT 'confirmed',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS locations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    latitude    REAL    NOT NULL,
    longitude   REAL    NOT NULL,
    accuracy_m  REAL,
    label       TEXT,
    recorded_at TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS briefings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    type       TEXT    NOT NULL DEFAULT 'morning',
    content    TEXT    NOT NULL,
    locale     TEXT    NOT NULL DEFAULT 'ko',
    delivered  INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    description TEXT,
    due_date    TEXT,
    priority    TEXT    NOT NULL DEFAULT 'normal',
    status      TEXT    NOT NULL DEFAULT 'pending',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS drive_files (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    google_file_id TEXT    UNIQUE,
    name           TEXT    NOT NULL,
    mime_type      TEXT,
    size_bytes     INTEGER,
    web_link       TEXT,
    parent_id      TEXT,
    synced_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS app_categories (
    app_name       TEXT    PRIMARY KEY,
    category       TEXT    NOT NULL,
    sub_category   TEXT,
    classified_by  TEXT    NOT NULL DEFAULT 'auto',
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS screen_texts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    app_name       TEXT,
    window_title   TEXT,
    extracted_text TEXT    NOT NULL,
    text_length    INTEGER,
    timestamp      TEXT    NOT NULL,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notifications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    type         TEXT    NOT NULL,
    title        TEXT    NOT NULL,
    message      TEXT    NOT NULL,
    reference_id INTEGER,
    delivered    INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_state (
    id               INTEGER PRIMARY KEY CHECK (id = 1),
    onboarding_stage TEXT    NOT NULL DEFAULT 'not_started',
    locale           TEXT    NOT NULL DEFAULT 'ko',
    google_token     TEXT,
    subscription     TEXT    NOT NULL DEFAULT 'free',
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""
