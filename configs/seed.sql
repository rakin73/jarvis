-- Jarvis v2 Seed Data
-- Run after schema.sql. Safe to re-run (INSERT OR IGNORE).

-- Default user
INSERT OR IGNORE INTO users (user_id, display_name, timezone) VALUES
    ('u_rakin', 'Rakin', 'America/Chicago');

-- Tool registry (what Jarvis can do)
INSERT OR IGNORE INTO tools (tool_id, tool_name, tool_category, description, risk_level, requires_confirm) VALUES
    -- Memory
    ('tool_memory_write',  'memory_write',  'memory', 'Store a memory item (fact, note, preference, runbook)', 'low', 0),
    ('tool_memory_query',  'memory_query',  'memory', 'Search memories by text, tags, or type',               'low', 0),
    ('tool_memory_pin',    'memory_pin',    'memory', 'Pin a memory to prevent expiration',                    'low', 0),
    ('tool_memory_forget', 'memory_forget', 'memory', 'Delete a memory item',                                 'medium', 1),

    -- System / macOS
    ('tool_shell',         'shell',         'system', 'Execute allowlisted shell commands',                    'high', 1),
    ('tool_open_app',      'open_app',      'system', 'Open a macOS application',                              'medium', 1),
    ('tool_open_url',      'open_url',      'system', 'Open a URL in default browser',                         'low', 0),
    ('tool_mac_control',   'mac_control',   'system', 'Control macOS (volume, clipboard, notifications, TTS)', 'medium', 0),

    -- IAM / Saviynt
    ('tool_saviynt_query', 'saviynt_query', 'iam',    'Generate Saviynt SQL queries from templates',           'low', 0),
    ('tool_saviynt_conn',  'saviynt_connector', 'iam', 'Generate REST connector JSON snippets',                'low', 0),

    -- Notes (legacy compat, now routes through memory_write)
    ('tool_notes',         'notes',         'memory', 'Quick notes (add, search, delete)',                     'low', 0);

-- Default preferences
INSERT OR IGNORE INTO user_preferences (user_id, pref_key, pref_value, confidence, source) VALUES
    ('u_rakin', 'response.style',       'concise',          1.0, 'explicit'),
    ('u_rakin', 'response.tone',        'senior_engineer',  1.0, 'explicit'),
    ('u_rakin', 'memory.web_cache_days','14',               1.0, 'explicit'),
    ('u_rakin', 'memory.auto_learn',    'true',             1.0, 'explicit'),
    ('u_rakin', 'tools.shell_confirm',  'true',             1.0, 'explicit');
