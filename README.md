# Jarvis v2 — Persistent Conversations, Semantic Memory & Approval Gates

## What's New in v2

| Feature | v1 | v2 |
|---------|----|----|
| Conversations | In-memory only | Persistent (SQLite threaded) |
| Memory | Flat notes table | Typed memory items (fact, preference, runbook, web_summary...) with importance, pinning, expiry |
| Search | Keyword only | Keyword + Chroma semantic (cosine similarity) |
| Tool Audit | `command_history` | Full `tool_runs` table with status, duration, error tracking |
| Approvals | None | Risk-gated: high-risk tools require interactive confirmation |
| Feedback | Basic rating | Rating + labels (wrong_tool, hallucination, great) + corrections |
| Skills | Flat table | JSON-based playbooks with success rate tracking |
| Preferences | key/value | key/value + confidence + source (explicit/inferred/imported) |
| Tool Registry | Hardcoded | DB-driven with risk levels and enable/disable |

## Quick Start

```bash
cd jarvis
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=sk-your-key
python -m app.main
```

## Architecture

```
jarvis/
├── app/
│   ├── main.py          # CLI with approval prompts
│   ├── brain.py         # LLM + conversation persistence + semantic context
│   └── router.py        # DB-driven tool dispatch + audit trail
├── tools/
│   ├── shell_tool.py    # Restricted shell (allowlist)
│   ├── notes_tool.py    # Quick notes (legacy compat)
│   ├── saviynt_tool.py  # Saviynt query templates + REST connector JSON
│   ├── mac_tool.py      # macOS control (AppleScript)
│   └── memory_tool.py   # Full memory CRUD + semantic search
├── memory/
│   ├── memory.py        # SQLite persistence (30+ tables)
│   ├── vectors.py       # Chroma vector store + OpenAI embeddings
│   ├── db.sqlite        # Auto-created
│   └── chroma_db/       # Auto-created
├── trainer/
│   └── feedback.py      # Rating, skills, improvement analysis
├── configs/
│   ├── policies.yaml    # LLM config, shell allowlist, Saviynt templates
│   ├── schema.sql       # Full v2 DDL
│   └── seed.sql         # Default user, tools, preferences
├── vault/               # File storage
│   ├── audio/in/out/
│   ├── web_cache/html/text/
│   ├── documents/imported/generated/
│   ├── finance/models/backtests/reports/
│   ├── screenshots/
│   └── attachments/
├── logs/
└── requirements.txt
```

## SQLite Schema (key tables)

**Core:** `users`, `user_preferences`
**Conversations:** `conversations`, `messages` (threaded, typed)
**Tools:** `tools` (registry), `tool_runs` (audit), `approvals` (gates)
**Memory:** `memory_items` (typed, importance, pinning, expiry), `memory_vectors` (Chroma registry)
**Learning:** `skills` (playbooks), `feedback` (labeled ratings)
**Contacts:** `contacts`
**Web:** `web_sources` (URL registry + memory links)
**Proactive:** `automations`, `alerts`

## Slash Commands

| Command | Description |
|---------|-------------|
| `/memory [query]` | Keyword search memories |
| `/recall <query>` | Semantic (AI) search memories |
| `/remember <text>` | Quick-store a memory |
| `/pin <id>` | Pin memory permanently |
| `/forget <id>` | Delete a memory |
| `/rate 1-5 [label] [correction]` | Rate with optional label |
| `/stats` | Full performance dashboard |
| `/convos` | Recent conversations |
| `/tools` | Registered tools with risk levels |
| `/skills` | Learned skills library |
| `/teach` | Teach new skill interactively |
| `/improve` | Get improvement suggestions |
| `/set key value` | Set preference |
| `/prefs` | View all preferences |

## Approval System

Tools are registered in the DB with risk levels:
- **low** (memory_query, web_search) → auto-execute
- **medium** (open_app, memory_forget) → confirm required
- **high** (shell, trade_submit, call_place) → always confirm

When the LLM tries to call a high-risk tool, the CLI prompts:
```
⚠️  Jarvis wants to use [shell]:
  Command: ls -la /tmp
Approve? (y/n)
→ y
```

## Semantic Memory

When you store memories (via chat or `/remember`), they're:
1. Saved to SQLite `memory_items` table
2. Embedded via OpenAI `text-embedding-3-small`
3. Stored in Chroma `memories` collection
4. Registered in `memory_vectors` for auditability

The brain automatically pulls relevant memories via cosine similarity and injects them into the system prompt.

## Phase 3 Roadmap

- [ ] Voice: Whisper STT + OpenAI TTS
- [ ] Browser: Playwright automation
- [ ] Finance: market_bars + models + predictions + backtests
- [ ] Calls: Twilio integration + call_sessions
- [ ] Bookings: Calendar API integration
- [ ] Scheduler: cron-based automations + alerts
