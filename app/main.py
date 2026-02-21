#!/usr/bin/env python3
"""
Jarvis v2 — AI assistant with persistent conversations, semantic memory,
tool audit trails, and approval gates.

Usage:
    python -m app.main
    OPENAI_API_KEY=sk-... python -m app.main

Commands:
    /help           — Show this help
    /rate <1-5> [label] [correction]  — Rate last response
    /stats          — Performance dashboard
    /memory [query] — Search memories (keyword)
    /recall [query] — Semantic search (AI similarity)
    /remember <text>— Quick-store a memory
    /pin <id>       — Pin a memory permanently
    /forget <id>    — Delete a memory
    /convos         — List recent conversations
    /tools          — List registered tools
    /skills         — List learned skills
    /teach          — Teach a new skill
    /improve        — Get improvement suggestions
    /set <k> <v>    — Set a preference
    /prefs          — View preferences
    /clear          — Start fresh conversation
    /quit           — Exit
"""

import os
import json
from app.brain import Brain
from trainer.feedback import Trainer
from memory.memory import (
    init_db, search_memories, store_memory, pin_memory, delete_memory,
    get_memory_stats, get_recent_conversations, get_all_preferences,
    set_preference, get_skills, get_all_tools, add_skill, DEFAULT_USER
)

# ── Colors ───────────────────────────────────────────────────────────

CYAN    = "\033[96m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
RED     = "\033[91m"
DIM     = "\033[2m"
BOLD    = "\033[1m"
RESET   = "\033[0m"
MAGENTA = "\033[95m"

def pj(t): print(f"\n{CYAN}Jarvis:{RESET} {t}")
def ps(t): print(f"{DIM}{t}{RESET}")
def pe(t): print(f"{RED}Error:{RESET} {t}")
def pk(t): print(f"{GREEN}✓{RESET} {t}")


def approval_prompt(prompt_text: str) -> bool:
    print(f"\n{YELLOW}{prompt_text}{RESET}")
    while True:
        resp = input(f"  {YELLOW}→{RESET} ").strip().lower()
        if resp in ("y", "yes", "approve"):
            return True
        if resp in ("n", "no", "deny"):
            return False
        print(f"  {DIM}Type 'y' or 'n'{RESET}")


def handle_slash(cmd: str, brain: Brain, trainer: Trainer):
    """Returns True if handled, None to quit."""
    parts = cmd.strip().split(maxsplit=3)
    command = parts[0].lower()

    if command in ("/quit", "/exit"):
        brain.end_current_conversation()
        pj("Shutting down. Goodnight, Rakin.")
        return None

    elif command == "/help":
        ps(__doc__)

    elif command == "/clear":
        brain.reset_conversation()
        pk("New conversation started.")

    elif command == "/rate":
        if not brain.conversation_id:
            pe("No active conversation.")
            return True
        try:
            rating = int(parts[1]) if len(parts) > 1 else 0
            label = parts[2] if len(parts) > 2 else None
            correction = parts[3] if len(parts) > 3 else None
            if not 1 <= rating <= 5:
                pe("Rating must be 1-5.")
                return True
            msg = brain.rate_last(rating, correction, label)
            pk(msg)
        except (ValueError, IndexError):
            pe("Usage: /rate <1-5> [label] [correction]")

    elif command == "/stats":
        stats = trainer.stats()
        ps(f"\n{'='*55}")
        ps(f"  {'JARVIS v2 DASHBOARD':^50}")
        ps(f"{'='*55}")
        ps(f"  Tool Runs:    {stats['tools']['total_runs']}")
        ps(f"  Success Rate: {stats['tools']['success_rate']}%")
        ps(f"  Avg Rating:   {stats['feedback']['avg_rating']}/5 ({stats['feedback']['total_feedback']} ratings)")
        ps(f"  Memories:     {stats['memory']['total']} ({stats['memory']['pinned']} pinned)")
        ps(f"  Skills:       {stats['skills_count']}")
        vs_status = '✓ active' if stats['vectors'].get('available') else '○ not configured'
        ps(f"  Vectors:      {vs_status}")
        if stats["tools"]["by_tool"]:
            ps("\n  Tool breakdown:")
            for name, data in stats["tools"]["by_tool"].items():
                rate = round(data["successes"] / data["count"] * 100) if data["count"] else 0
                ps(f"    {name}: {data['count']} runs ({rate}% success)")
        if stats["memory"]["by_type"]:
            ps("\n  Memory types:")
            for mtype, count in stats["memory"]["by_type"].items():
                ps(f"    {mtype}: {count}")
        if stats["top_skills"]:
            ps("\n  Top skills:")
            for s in stats["top_skills"]:
                ps(f"    {s['name']} (used {s['times_used']}x, {s['success_rate']:.0%})")
        ps("=" * 55)

    elif command == "/memory":
        query = " ".join(parts[1:]) if len(parts) > 1 else None
        results = search_memories(query=query, limit=15)
        if not results:
            ps("No memories found." + (" Try /recall for semantic search." if query else ""))
        else:
            ps(f"\n{'='*55}")
            ps(f"  Memories" + (f" matching: {query}" if query else ""))
            ps(f"{'='*55}")
            for m in results:
                pin = "📌" if m["pin_status"] else "  "
                tags = f" [{m['tags']}]" if m.get("tags") else ""
                imp = "★" * m["importance"]
                ps(f"  {pin} {m['memory_id']} [{m['memory_type']}] {imp}")
                ps(f"     {m.get('title') or m['body'][:80]}{tags}")
            ps("=" * 55)

    elif command == "/recall":
        query = " ".join(parts[1:]) if len(parts) > 1 else None
        if not query:
            pe("Usage: /recall <search query>")
            return True
        try:
            from memory.vectors import VectorStore
            vs = VectorStore()
            if not vs.available:
                ps("Vector store not available. Falling back to keyword search.")
                for m in search_memories(query=query, limit=5):
                    ps(f"  • {m.get('title') or m['body'][:80]}")
            else:
                results = vs.search(query, top_k=5)
                if not results:
                    ps("No semantic matches found.")
                else:
                    ps(f"\n  Semantic matches for: '{query}'")
                    ps(f"  {'─'*45}")
                    for r in results:
                        bar = "█" * int(r["score"] * 10) + "░" * (10 - int(r["score"] * 10))
                        ps(f"  {bar} {r['score']:.2f}  {r['text'][:70]}")
        except Exception as e:
            pe(f"Semantic search failed: {e}")

    elif command == "/remember":
        text = " ".join(parts[1:]) if len(parts) > 1 else None
        if not text:
            pe("Usage: /remember <text>")
            return True
        mem_id = store_memory(body=text, memory_type="note", source="user")
        try:
            from memory.vectors import VectorStore
            vs = VectorStore()
            if vs.available:
                vs.store(mem_id, text, metadata={"memory_type": "note", "source": "user"})
        except Exception:
            pass
        pk(f"Stored: {mem_id}")

    elif command == "/pin":
        if len(parts) < 2:
            pe("Usage: /pin <memory_id>")
            return True
        ok = pin_memory(parts[1])
        pk(f"Memory {parts[1]} {'pinned' if ok else 'not found'}.")

    elif command == "/forget":
        if len(parts) < 2:
            pe("Usage: /forget <memory_id>")
            return True
        try:
            from memory.vectors import VectorStore
            vs = VectorStore()
            if vs.available:
                vs.delete(parts[1])
        except Exception:
            pass
        ok = delete_memory(parts[1])
        pk(f"Memory {parts[1]} {'deleted' if ok else 'not found'}.")

    elif command == "/convos":
        convos = get_recent_conversations(limit=10)
        if not convos:
            ps("No conversations yet.")
        else:
            ps(f"\n  Recent Conversations")
            ps(f"  {'─'*45}")
            for c in convos:
                title = c.get("title") or "(untitled)"
                ps(f"  {c['conversation_id']}  {title}  ({c['msg_count']} msgs)  {c['started_at']}")

    elif command == "/tools":
        tools = get_all_tools()
        if not tools:
            ps("No tools registered.")
        else:
            ps(f"\n  Registered Tools")
            ps(f"  {'─'*50}")
            for t in tools:
                risk_color = RED if t["risk_level"] == "high" else YELLOW if t["risk_level"] == "medium" else GREEN
                confirm = "🔒" if t["requires_confirm"] else "  "
                ps(f"  {confirm} {t['tool_name']:<25} {risk_color}{t['risk_level']:<8}{RESET} [{t['tool_category']}]")
                if t.get("description"):
                    ps(f"     {DIM}{t['description'][:60]}{RESET}")

    elif command == "/skills":
        skills = get_skills()
        if not skills:
            ps("No skills learned yet. Use /teach to add one.")
        else:
            ps(f"\n  Skills Library")
            ps(f"  {'─'*45}")
            for s in skills:
                ps(f"  {s['skill_id']}  {s['name']}")
                ps(f"     {s['description'] or ''}")
                ps(f"     Used {s['times_used']}x | Success: {s['success_rate']:.0%}")

    elif command == "/teach":
        ps("Teach Jarvis a new skill:")
        name = input(f"  {YELLOW}Name:{RESET} ").strip()
        description = input(f"  {YELLOW}Description:{RESET} ").strip()
        triggers = input(f"  {YELLOW}Trigger examples (comma-sep):{RESET} ").strip() or None
        steps = input(f"  {YELLOW}Steps (tool chain, JSON or description):{RESET} ").strip()
        if name and description and steps:
            sid = add_skill(name, description, steps, triggers)
            pk(f"Skill '{name}' learned! ({sid})")
        else:
            pe("Name, description, and steps are required.")

    elif command == "/improve":
        improvements = trainer.get_improvements()
        ps(f"\n  Improvement Suggestions")
        ps(f"  {'─'*45}")
        for s in improvements["suggestions"]:
            ps(f"  → {s}")

    elif command == "/set":
        if len(parts) >= 3:
            set_preference(parts[1], " ".join(parts[2:]))
            pk(f"Preference '{parts[1]}' set.")
        else:
            pe("Usage: /set <key> <value>")

    elif command == "/prefs":
        prefs = get_all_preferences()
        if prefs:
            ps(f"\n  Preferences")
            ps(f"  {'─'*45}")
            for k, v in prefs.items():
                src = f" ({v['source']}, conf={v['confidence']})" if v.get("source") else ""
                ps(f"  {k}: {v['value']}{src}")
        else:
            ps("No preferences set. Use /set <key> <value>")

    else:
        pe(f"Unknown command: {command}. Type /help for commands.")

    return True


# ── Main Loop ────────────────────────────────────────────────────────

def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        pe("OPENAI_API_KEY not set.")
        ps("Set it with: export OPENAI_API_KEY=sk-...")
        sys.exit(1)

    init_db()
    brain = Brain(api_key=api_key, approval_callback=approval_prompt)
    trainer = Trainer()
    brain.start_conversation(title="CLI session")

    print(f"""
{CYAN}{'='*55}
     ╦╔═╗╦═╗╦  ╦╦╔═╗  ┬  ┬┌─┐
     ║╠═╣╠╦╝╚╗╔╝║╚═╗  └┐┌┘┌─┘
    ╚╝╩ ╩╩╚═ ╚╝ ╩╚═╝   └┘ └─┘
{'='*55}{RESET}
  {MAGENTA}v2{RESET} {DIM}— Conversations • Semantic Memory • Approvals{RESET}
  {DIM}Type /help for commands, /quit to exit{RESET}
""")

    while True:
        try:
            user_input = input(f"\n{GREEN}Rakin →{RESET} ").strip()
            if not user_input:
                continue

            if user_input.startswith("/"):
                result = handle_slash(user_input, brain, trainer)
                if result is None:
                    break
                continue

            ps("  thinking...")
            response = brain.think(user_input)
            pj(response)

        except KeyboardInterrupt:
            brain.end_current_conversation()
            pj("\nShutting down. Goodnight, Rakin.")
            break
        except EOFError:
            break
        except Exception as e:
            pe(f"Unexpected error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
