"""
Jarvis v2 Memory Module
Full persistence layer: conversations, messages, memory items, tool runs,
approvals, and Chroma vector search.
"""

import sqlite3
import json
import os
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

# ── Paths ────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "memory", "db.sqlite")
SCHEMA_PATH = os.path.join(BASE_DIR, "configs", "schema.sql")
SEED_PATH = os.path.join(BASE_DIR, "configs", "seed.sql")

DEFAULT_USER = "u_rakin"


def _uid(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# ── Connection ───────────────────────────────────────────────────────

def get_connection(db_path: str = None) -> sqlite3.Connection:
    db = db_path or DB_PATH
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str = None):
    """Create all tables from schema.sql and run seed.sql."""
    db = db_path or DB_PATH
    # Ensure directories exist
    os.makedirs(os.path.dirname(db), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, 'logs'), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, 'vault'), exist_ok=True)
    conn = get_connection(db)
    if os.path.exists(SCHEMA_PATH):
        with open(SCHEMA_PATH) as f:
            conn.executescript(f.read())
    if os.path.exists(SEED_PATH):
        with open(SEED_PATH) as f:
            conn.executescript(f.read())
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════════
# CONVERSATIONS & MESSAGES
# ═══════════════════════════════════════════════════════════════════════

def create_conversation(user_id: str = DEFAULT_USER, title: str = None,
                        mode: str = "text", db_path: str = None) -> str:
    conn = get_connection(db_path)
    conv_id = _uid("conv_")
    conn.execute(
        "INSERT INTO conversations (conversation_id, user_id, title, mode) VALUES (?,?,?,?)",
        (conv_id, user_id, title, mode)
    )
    conn.commit()
    conn.close()
    return conv_id


def end_conversation(conversation_id: str, db_path: str = None):
    conn = get_connection(db_path)
    conn.execute(
        "UPDATE conversations SET ended_at = ? WHERE conversation_id = ?",
        (datetime.now().isoformat(), conversation_id)
    )
    conn.commit()
    conn.close()


def add_message(conversation_id: str, role: str, content: str,
                content_type: str = "text", tool_call_id: str = None,
                tool_name: str = None, tool_input: str = None,
                db_path: str = None) -> str:
    conn = get_connection(db_path)
    msg_id = _uid("msg_")
    conn.execute(
        """INSERT INTO messages 
           (message_id, conversation_id, role, content, content_type, 
            tool_call_id, tool_name, tool_input) 
           VALUES (?,?,?,?,?,?,?,?)""",
        (msg_id, conversation_id, role, content, content_type,
         tool_call_id, tool_name, tool_input)
    )
    conn.commit()
    conn.close()
    return msg_id


def get_conversation_messages(conversation_id: str, limit: int = 50,
                               db_path: str = None) -> List[Dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        """SELECT * FROM messages WHERE conversation_id = ? 
           ORDER BY created_at ASC LIMIT ?""",
        (conversation_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_conversations(user_id: str = DEFAULT_USER, limit: int = 10,
                              db_path: str = None) -> List[Dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        """SELECT c.*, COUNT(m.message_id) as msg_count
           FROM conversations c
           LEFT JOIN messages m ON c.conversation_id = m.conversation_id
           WHERE c.user_id = ?
           GROUP BY c.conversation_id
           ORDER BY c.started_at DESC LIMIT ?""",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════
# TOOL RUNS & APPROVALS
# ═══════════════════════════════════════════════════════════════════════

def get_tool_by_name(tool_name: str, db_path: str = None) -> Optional[Dict]:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM tools WHERE tool_name = ? AND enabled = 1", (tool_name,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_tools(db_path: str = None) -> List[Dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM tools WHERE enabled = 1 ORDER BY tool_category, tool_name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_tool_run(conversation_id: str, tool_id: str, input_json: str,
                    message_id: str = None, status: str = "running",
                    db_path: str = None) -> str:
    conn = get_connection(db_path)
    run_id = _uid("tr_")
    conn.execute(
        """INSERT INTO tool_runs 
           (tool_run_id, conversation_id, message_id, tool_id, status, input_json)
           VALUES (?,?,?,?,?,?)""",
        (run_id, conversation_id, message_id, tool_id, status, input_json)
    )
    conn.commit()
    conn.close()
    return run_id


def complete_tool_run(tool_run_id: str, status: str, output_json: str = None,
                      error_text: str = None, duration_ms: int = None,
                      db_path: str = None):
    conn = get_connection(db_path)
    conn.execute(
        """UPDATE tool_runs 
           SET status = ?, output_json = ?, error_text = ?, duration_ms = ?,
               finished_at = ?
           WHERE tool_run_id = ?""",
        (status, output_json, error_text, duration_ms,
         datetime.now().isoformat(), tool_run_id)
    )
    conn.commit()
    conn.close()


def create_approval(tool_run_id: str, user_id: str, prompt_text: str,
                    db_path: str = None) -> str:
    conn = get_connection(db_path)
    appr_id = _uid("appr_")
    conn.execute(
        """INSERT INTO approvals 
           (approval_id, tool_run_id, user_id, prompt_text, decision)
           VALUES (?,?,?,?,?)""",
        (appr_id, tool_run_id, user_id, prompt_text, "pending")
    )
    conn.commit()
    conn.close()
    return appr_id


def resolve_approval(approval_id: str, decision: str, user_response: str = None,
                     db_path: str = None):
    conn = get_connection(db_path)
    conn.execute(
        """UPDATE approvals 
           SET decision = ?, user_response = ?, decided_at = ?
           WHERE approval_id = ?""",
        (decision, user_response, datetime.now().isoformat(), approval_id)
    )
    conn.commit()
    conn.close()


def get_pending_approvals(user_id: str = DEFAULT_USER, db_path: str = None) -> List[Dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        """SELECT a.*, tr.tool_id, tr.input_json, t.tool_name, t.risk_level
           FROM approvals a
           JOIN tool_runs tr ON a.tool_run_id = tr.tool_run_id
           JOIN tools t ON tr.tool_id = t.tool_id
           WHERE a.user_id = ? AND a.decision = 'pending'
           ORDER BY a.decided_at DESC""",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_tool_run_stats(db_path: str = None) -> Dict:
    conn = get_connection(db_path)
    total = conn.execute("SELECT COUNT(*) as c FROM tool_runs").fetchone()["c"]
    success = conn.execute(
        "SELECT COUNT(*) as c FROM tool_runs WHERE status='success'"
    ).fetchone()["c"]
    by_tool = conn.execute(
        """SELECT t.tool_name, COUNT(*) as count, 
                  SUM(CASE WHEN tr.status='success' THEN 1 ELSE 0 END) as successes
           FROM tool_runs tr JOIN tools t ON tr.tool_id = t.tool_id
           GROUP BY t.tool_name ORDER BY count DESC"""
    ).fetchall()
    conn.close()
    return {
        "total_runs": total,
        "success_rate": round(success / total * 100, 1) if total > 0 else 0,
        "by_tool": {r["tool_name"]: {"count": r["count"], "successes": r["successes"]} for r in by_tool}
    }


# ═══════════════════════════════════════════════════════════════════════
# MEMORY ITEMS
# ═══════════════════════════════════════════════════════════════════════

def store_memory(body: str, memory_type: str = "note", title: str = None,
                 tags: str = None, importance: int = 3, pin: bool = False,
                 source: str = "user", source_ref: str = None,
                 expires_at: str = None, user_id: str = DEFAULT_USER,
                 db_path: str = None) -> str:
    conn = get_connection(db_path)
    mem_id = _uid("mem_")
    conn.execute(
        """INSERT INTO memory_items 
           (memory_id, user_id, memory_type, title, body, tags, importance,
            pin_status, source, source_ref, expires_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (mem_id, user_id, memory_type, title, body, tags, importance,
         int(pin), source, source_ref, expires_at)
    )
    conn.commit()
    conn.close()
    return mem_id


def search_memories(query: str = None, memory_type: str = None,
                    tags: str = None, min_importance: int = None,
                    limit: int = 20, user_id: str = DEFAULT_USER,
                    db_path: str = None) -> List[Dict]:
    conn = get_connection(db_path)
    sql = "SELECT * FROM memory_items WHERE user_id = ?"
    params: list = [user_id]
    sql += " AND (expires_at IS NULL OR expires_at > ? OR pin_status = 1)"
    params.append(datetime.now().isoformat())
    if query:
        sql += " AND (body LIKE ? OR title LIKE ?)"
        params.extend([f"%{query}%", f"%{query}%"])
    if memory_type:
        sql += " AND memory_type = ?"
        params.append(memory_type)
    if tags:
        for tag in tags.split(","):
            sql += " AND tags LIKE ?"
            params.append(f"%{tag.strip()}%")
    if min_importance:
        sql += " AND importance >= ?"
        params.append(min_importance)
    sql += " ORDER BY importance DESC, updated_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_memory(memory_id: str, db_path: str = None) -> Optional[Dict]:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM memory_items WHERE memory_id = ?", (memory_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_memory(memory_id: str, **kwargs) -> bool:
    db_path = kwargs.pop("db_path", None)
    conn = get_connection(db_path)
    allowed = {"title", "body", "tags", "importance", "pin_status", "expires_at", "memory_type"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        conn.close()
        return False
    updates["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [memory_id]
    cursor = conn.execute(
        f"UPDATE memory_items SET {set_clause} WHERE memory_id = ?", values
    )
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


def pin_memory(memory_id: str, db_path: str = None) -> bool:
    return update_memory(memory_id, pin_status=1, db_path=db_path)


def delete_memory(memory_id: str, db_path: str = None) -> bool:
    conn = get_connection(db_path)
    cursor = conn.execute("DELETE FROM memory_items WHERE memory_id = ?", (memory_id,))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


def get_memory_stats(user_id: str = DEFAULT_USER, db_path: str = None) -> Dict:
    conn = get_connection(db_path)
    total = conn.execute(
        "SELECT COUNT(*) as c FROM memory_items WHERE user_id = ?", (user_id,)
    ).fetchone()["c"]
    by_type = conn.execute(
        "SELECT memory_type, COUNT(*) as count FROM memory_items WHERE user_id = ? GROUP BY memory_type",
        (user_id,)
    ).fetchall()
    pinned = conn.execute(
        "SELECT COUNT(*) as c FROM memory_items WHERE user_id = ? AND pin_status = 1",
        (user_id,)
    ).fetchone()["c"]
    conn.close()
    return {"total": total, "pinned": pinned, "by_type": {r["memory_type"]: r["count"] for r in by_type}}


# ═══════════════════════════════════════════════════════════════════════
# USER PREFERENCES
# ═══════════════════════════════════════════════════════════════════════

def set_preference(key: str, value: str, source: str = "explicit",
                   confidence: float = 1.0, user_id: str = DEFAULT_USER,
                   db_path: str = None):
    conn = get_connection(db_path)
    conn.execute(
        """INSERT OR REPLACE INTO user_preferences 
           (user_id, pref_key, pref_value, confidence, source, updated_at) 
           VALUES (?,?,?,?,?,?)""",
        (user_id, key, value, confidence, source, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_preference(key: str, default: str = None, user_id: str = DEFAULT_USER,
                   db_path: str = None) -> Optional[str]:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT pref_value FROM user_preferences WHERE user_id = ? AND pref_key = ?",
        (user_id, key)
    ).fetchone()
    conn.close()
    return row["pref_value"] if row else default


def get_all_preferences(user_id: str = DEFAULT_USER, db_path: str = None) -> Dict:
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT pref_key, pref_value, confidence, source FROM user_preferences WHERE user_id = ?",
        (user_id,)
    ).fetchall()
    conn.close()
    return {r["pref_key"]: {"value": r["pref_value"], "confidence": r["confidence"], "source": r["source"]}
            for r in rows}


# ═══════════════════════════════════════════════════════════════════════
# SKILLS
# ═══════════════════════════════════════════════════════════════════════

def add_skill(name: str, description: str, steps_json: str,
              trigger_examples: str = None, user_id: str = DEFAULT_USER,
              db_path: str = None) -> str:
    conn = get_connection(db_path)
    skill_id = _uid("skill_")
    conn.execute(
        """INSERT INTO skills 
           (skill_id, user_id, name, description, trigger_examples, steps_json)
           VALUES (?,?,?,?,?,?)""",
        (skill_id, user_id, name, description, trigger_examples, steps_json)
    )
    conn.commit()
    conn.close()
    return skill_id


def get_skills(user_id: str = DEFAULT_USER, db_path: str = None) -> List[Dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM skills WHERE user_id = ? ORDER BY times_used DESC", (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def record_skill_use(skill_id: str, success: bool, db_path: str = None):
    conn = get_connection(db_path)
    skill = conn.execute("SELECT * FROM skills WHERE skill_id = ?", (skill_id,)).fetchone()
    if skill:
        times = skill["times_used"] + 1
        successes = (skill["success_rate"] * skill["times_used"] + (1 if success else 0))
        new_rate = successes / times if times > 0 else 0
        conn.execute(
            """UPDATE skills SET times_used = ?, success_rate = ?, 
               last_used_at = ?, updated_at = ? WHERE skill_id = ?""",
            (times, round(new_rate, 3), datetime.now().isoformat(),
             datetime.now().isoformat(), skill_id)
        )
        conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════════
# FEEDBACK
# ═══════════════════════════════════════════════════════════════════════

def add_feedback(conversation_id: str, rating: int, user_id: str = DEFAULT_USER,
                 message_id: str = None, tool_run_id: str = None,
                 correction_text: str = None, label: str = None,
                 db_path: str = None) -> str:
    conn = get_connection(db_path)
    fb_id = _uid("fb_")
    conn.execute(
        """INSERT INTO feedback 
           (feedback_id, conversation_id, message_id, tool_run_id, 
            user_id, rating, correction_text, label)
           VALUES (?,?,?,?,?,?,?,?)""",
        (fb_id, conversation_id, message_id, tool_run_id,
         user_id, rating, correction_text, label)
    )
    conn.commit()
    conn.close()
    return fb_id


def get_feedback_summary(user_id: str = DEFAULT_USER, db_path: str = None) -> Dict:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT COUNT(*) as total, AVG(rating) as avg_rating FROM feedback WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    labels = conn.execute(
        "SELECT label, COUNT(*) as count FROM feedback WHERE user_id = ? AND label IS NOT NULL GROUP BY label",
        (user_id,)
    ).fetchall()
    conn.close()
    return {
        "total_feedback": row["total"],
        "avg_rating": round(row["avg_rating"] or 0, 2),
        "by_label": {r["label"]: r["count"] for r in labels}
    }


# ═══════════════════════════════════════════════════════════════════════
# WEB SOURCES & CONTACTS
# ═══════════════════════════════════════════════════════════════════════

def store_web_source(url: str, title: str = None, summary_memory_id: str = None,
                     raw_path: str = None, db_path: str = None) -> str:
    from urllib.parse import urlparse
    conn = get_connection(db_path)
    source_id = _uid("web_")
    domain = urlparse(url).netloc
    content_hash = hashlib.md5(url.encode()).hexdigest()
    conn.execute(
        """INSERT INTO web_sources 
           (source_id, url, title, domain, content_hash, raw_path, summary_memory_id)
           VALUES (?,?,?,?,?,?,?)""",
        (source_id, url, title, domain, content_hash, raw_path, summary_memory_id)
    )
    conn.commit()
    conn.close()
    return source_id


def add_contact(display_name: str, phone: str = None, email: str = None,
                notes: str = None, user_id: str = DEFAULT_USER,
                db_path: str = None) -> str:
    conn = get_connection(db_path)
    cid = _uid("ct_")
    conn.execute(
        "INSERT INTO contacts (contact_id, user_id, display_name, phone_e164, email, notes) VALUES (?,?,?,?,?,?)",
        (cid, user_id, display_name, phone, email, notes)
    )
    conn.commit()
    conn.close()
    return cid


def search_contacts(query: str = None, user_id: str = DEFAULT_USER,
                     db_path: str = None) -> List[Dict]:
    conn = get_connection(db_path)
    sql = "SELECT * FROM contacts WHERE user_id = ?"
    params: list = [user_id]
    if query:
        sql += " AND (display_name LIKE ? OR email LIKE ? OR phone_e164 LIKE ?)"
        params.extend([f"%{query}%"] * 3)
    sql += " ORDER BY display_name"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════
# CONTEXT BUILDER
# ═══════════════════════════════════════════════════════════════════════

def build_context(user_id: str = DEFAULT_USER, db_path: str = None) -> str:
    parts = []

    prefs = get_all_preferences(user_id, db_path)
    if prefs:
        parts.append("## User Preferences")
        for k, v in prefs.items():
            parts.append(f"- {k}: {v['value']}")

    memories = search_memories(min_importance=4, limit=10, user_id=user_id, db_path=db_path)
    if memories:
        parts.append("\n## Key Memories")
        for m in memories:
            pin = "📌 " if m["pin_status"] else ""
            parts.append(f"- {pin}[{m['memory_type']}] {m.get('title') or m['body'][:80]}")

    conn = get_connection(db_path)
    recent_runs = conn.execute(
        """SELECT tr.*, t.tool_name FROM tool_runs tr
           JOIN tools t ON tr.tool_id = t.tool_id
           ORDER BY tr.started_at DESC LIMIT 5"""
    ).fetchall()
    conn.close()
    if recent_runs:
        parts.append("\n## Recent Tool Activity")
        for r in recent_runs:
            status_icon = "✓" if r["status"] == "success" else "✗"
            parts.append(f"- [{status_icon}] {r['tool_name']}")

    skills = get_skills(user_id, db_path)
    if skills:
        parts.append("\n## Learned Skills")
        for s in skills[:5]:
            parts.append(f"- {s['name']} (used {s['times_used']}x, {s['success_rate']:.0%} success)")

    return "\n".join(parts) if parts else "No memory context yet."


# ═══════════════════════════════════════════════════════════════════════
# MAINTENANCE
# ═══════════════════════════════════════════════════════════════════════

def cleanup_expired(db_path: str = None) -> int:
    conn = get_connection(db_path)
    cursor = conn.execute(
        "DELETE FROM memory_items WHERE expires_at IS NOT NULL AND expires_at < ? AND pin_status = 0",
        (datetime.now().isoformat(),)
    )
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count


# Initialize on import
init_db()
