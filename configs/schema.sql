-- Jarvis v2 Schema
-- Run once. All tables use IF NOT EXISTS so it's safe to re-run.
PRAGMA foreign_keys = ON;

-- =========================
-- Core identity / settings
-- =========================
CREATE TABLE IF NOT EXISTS users (
    user_id         TEXT PRIMARY KEY,
    display_name    TEXT,
    timezone        TEXT DEFAULT 'America/Chicago',
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id         TEXT NOT NULL,
    pref_key        TEXT NOT NULL,
    pref_value      TEXT NOT NULL,
    confidence      REAL DEFAULT 1.0,
    source          TEXT,                   -- "explicit","inferred","imported"
    updated_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, pref_key),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- =========================
-- Conversations & messages
-- =========================
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    title           TEXT,
    mode            TEXT DEFAULT 'text',    -- "voice","text","mixed"
    started_at      TEXT DEFAULT (datetime('now')),
    ended_at        TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS messages (
    message_id      TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL,           -- "user","assistant","system","tool"
    content         TEXT NOT NULL,
    content_type    TEXT DEFAULT 'text',     -- "text","json","markdown"
    tool_call_id    TEXT,                    -- links tool result to its call
    tool_name       TEXT,                    -- which tool was called
    tool_input      TEXT,                    -- JSON args sent to tool
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(conversation_id, role);

-- =========================
-- Tools registry & execution audit
-- =========================
CREATE TABLE IF NOT EXISTS tools (
    tool_id             TEXT PRIMARY KEY,
    tool_name           TEXT NOT NULL UNIQUE,
    tool_category       TEXT NOT NULL,       -- "web","system","memory","communications","calendar","finance","iam"
    description         TEXT,
    risk_level          TEXT DEFAULT 'medium',-- "low","medium","high"
    requires_confirm    INTEGER DEFAULT 1,
    enabled             INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS tool_runs (
    tool_run_id     TEXT PRIMARY KEY,
    conversation_id TEXT,
    message_id      TEXT,
    tool_id         TEXT NOT NULL,
    status          TEXT NOT NULL,           -- "planned","running","success","failed","cancelled","needs_confirm"
    input_json      TEXT NOT NULL,
    output_json     TEXT,
    error_text      TEXT,
    duration_ms     INTEGER,
    started_at      TEXT DEFAULT (datetime('now')),
    finished_at     TEXT,
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE SET NULL,
    FOREIGN KEY (message_id) REFERENCES messages(message_id) ON DELETE SET NULL,
    FOREIGN KEY (tool_id) REFERENCES tools(tool_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_tool_runs_conv ON tool_runs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_tool_runs_status ON tool_runs(status);

-- Approvals for risky actions
CREATE TABLE IF NOT EXISTS approvals (
    approval_id     TEXT PRIMARY KEY,
    tool_run_id     TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    prompt_text     TEXT NOT NULL,
    user_response   TEXT,
    decision        TEXT NOT NULL,           -- "approved","denied","expired"
    decided_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (tool_run_id) REFERENCES tool_runs(tool_run_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- =========================
-- Memory system (enhanced)
-- =========================
CREATE TABLE IF NOT EXISTS memory_items (
    memory_id       TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    memory_type     TEXT NOT NULL,           -- "fact","preference","skill","note","web_summary","runbook","contact","finance_rule"
    title           TEXT,
    body            TEXT NOT NULL,
    tags            TEXT,                    -- comma-separated
    importance      INTEGER DEFAULT 3,       -- 1..5
    pin_status      INTEGER DEFAULT 0,       -- 0/1 (permanent vs can expire)
    source          TEXT,                    -- "user","assistant","web","import"
    source_ref      TEXT,                    -- url, file path, tool_run_id
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    expires_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_user ON memory_items(user_id, memory_type);
CREATE INDEX IF NOT EXISTS idx_memory_tags ON memory_items(tags);
CREATE INDEX IF NOT EXISTS idx_memory_importance ON memory_items(importance DESC);

-- Vector index registry (actual vectors in Chroma)
CREATE TABLE IF NOT EXISTS memory_vectors (
    vector_id       TEXT PRIMARY KEY,
    memory_id       TEXT NOT NULL,
    provider        TEXT NOT NULL,           -- "chroma"
    collection_name TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    dimension       INTEGER NOT NULL,
    external_ref    TEXT NOT NULL,           -- id in vector DB
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (memory_id) REFERENCES memory_items(memory_id) ON DELETE CASCADE
);

-- Skills (executable playbooks)
CREATE TABLE IF NOT EXISTS skills (
    skill_id        TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    trigger_examples TEXT,
    steps_json      TEXT NOT NULL,
    success_rate    REAL DEFAULT 0.0,
    times_used      INTEGER DEFAULT 0,
    last_used_at    TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Feedback
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id     TEXT PRIMARY KEY,
    conversation_id TEXT,
    message_id      TEXT,
    tool_run_id     TEXT,
    user_id         TEXT NOT NULL,
    rating          INTEGER,
    correction_text TEXT,
    label           TEXT,                    -- "wrong_tool","bad_sources","tone","hallucination","great"
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- =========================
-- Contacts
-- =========================
CREATE TABLE IF NOT EXISTS contacts (
    contact_id      TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    phone_e164      TEXT,
    email           TEXT,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- =========================
-- Web knowledge capture
-- =========================
CREATE TABLE IF NOT EXISTS web_sources (
    source_id           TEXT PRIMARY KEY,
    url                 TEXT NOT NULL,
    title               TEXT,
    domain              TEXT,
    fetched_at          TEXT DEFAULT (datetime('now')),
    content_hash        TEXT,
    raw_path            TEXT,
    summary_memory_id   TEXT,
    FOREIGN KEY (summary_memory_id) REFERENCES memory_items(memory_id) ON DELETE SET NULL
);

-- =========================
-- Automations & alerts (proactive Jarvis)
-- =========================
CREATE TABLE IF NOT EXISTS automations (
    automation_id   TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    schedule_cron   TEXT,
    enabled         INTEGER DEFAULT 1,
    task_json       TEXT NOT NULL,
    last_run_at     TEXT,
    next_run_at     TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id        TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    alert_type      TEXT NOT NULL,
    condition_json  TEXT NOT NULL,
    status          TEXT NOT NULL,           -- "active","triggered","paused"
    last_triggered_at TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
