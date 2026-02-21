"""
Jarvis v2 Router
DB-driven tool registry with approval gates and full audit trail.
"""

import json
import time
from typing import Dict, Optional, Tuple, List
from tools import shell_tool, notes_tool, saviynt_tool, mac_tool, memory_tool
from memory.memory import (
    get_tool_by_name, create_tool_run, complete_tool_run,
    create_approval, get_all_tools, get_connection
)

# ── Tool Executors ───────────────────────────────────────────────────
# Maps tool_name (from DB) → module with run() function

TOOL_EXECUTORS = {
    "shell":              shell_tool,
    "notes":              notes_tool,
    "saviynt_query":      saviynt_tool,
    "saviynt_connector":  saviynt_tool,
    "mac_control":        mac_tool,
    "open_app":           mac_tool,
    "memory_write":       memory_tool,
    "memory_query":       memory_tool,
    "memory_pin":         memory_tool,
    "memory_forget":      memory_tool,
}

# ── OpenAI Function Definitions ─────────────────────────────────────
# These are the tools the LLM sees. They map to the executors above.

LLM_TOOL_DEFS = [
    shell_tool.TOOL_DEF,
    notes_tool.TOOL_DEF,
    saviynt_tool.TOOL_DEF,
    mac_tool.TOOL_DEF,
    memory_tool.TOOL_DEF,
]


def get_openai_tools() -> list:
    """Get tool definitions formatted for OpenAI function calling."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"]
            }
        }
        for t in LLM_TOOL_DEFS
    ]


# ── Tool Name Mapping ───────────────────────────────────────────────
# LLM tool name → DB tool_name (for looking up risk/confirm settings)

LLM_TO_DB_TOOL = {
    "shell":    "shell",
    "notes":    "notes",
    "saviynt":  "saviynt_query",
    "mac":      "mac_control",
    "memory":   "memory_write",  # default; overridden by action
}

# Memory actions map to specific DB tool entries
MEMORY_ACTION_TO_DB = {
    "write":    "memory_write",
    "query":    "memory_query",
    "semantic": "memory_query",
    "pin":      "memory_pin",
    "update":   "memory_write",
    "delete":   "memory_forget",
    "stats":    "memory_query",
}

# mac actions map to specific DB tool entries
MAC_ACTION_TO_DB = {
    'open_app': 'open_app',
    'open_url': 'open_url',
    'notify': 'mac_control',
    'screenshot': 'mac_control',
}


def _resolve_db_tool(llm_tool_name: str, arguments: Dict) -> str:
    """Resolve LLM tool name + arguments to a DB tool_name."""
    if llm_tool_name == 'memory':
        action = arguments.get('action', 'query')
        return MEMORY_ACTION_TO_DB.get(action, 'memory_query')
    if llm_tool_name == 'mac':
        action = arguments.get('action', 'mac_control')
        return MAC_ACTION_TO_DB.get(action, 'mac_control')
    return LLM_TO_DB_TOOL.get(llm_tool_name, llm_tool_name)


def check_approval_needed(llm_tool_name: str, arguments: Dict) -> Tuple[bool, Optional[Dict]]:
    """
    Check if a tool call requires user approval before execution.
    Returns (needs_approval, tool_info).
    """
    db_tool_name = _resolve_db_tool(llm_tool_name, arguments)
    tool_info = get_tool_by_name(db_tool_name)

    if tool_info and tool_info.get("requires_confirm"):
        return True, tool_info

    return False, tool_info


def execute_tool(tool_name: str, arguments: Dict,
                 conversation_id: str = None) -> Tuple[Dict, int, Optional[str]]:
    """
    Execute a tool by LLM name with given arguments.
    Creates a tool_run audit record.
    
    Returns:
        (result_dict, duration_ms, tool_run_id)
    """
    # Resolve DB tool for audit
    db_tool_name = _resolve_db_tool(tool_name, arguments)
    tool_info = get_tool_by_name(db_tool_name)
    # Ensure tool exists to satisfy FK constraints in tool_runs
    if not tool_info:
        tool_id = f"tool_{db_tool_name}"
        try:
            conn = get_connection()
            conn.execute("INSERT OR IGNORE INTO tools (tool_id, tool_name, tool_category, description, risk_level, requires_confirm, enabled) VALUES (?,?,?,?,?,?,1)",
                         (tool_id, db_tool_name, 'system', 'Auto-registered tool', 'high', 1))
            conn.commit()
            conn.close()
        except Exception:
            pass
        tool_info = get_tool_by_name(db_tool_name)
    tool_id = tool_info["tool_id"] if tool_info else f"tool_{db_tool_name}"

    # Create audit record
    tool_run_id = None
    if conversation_id:
        tool_run_id = create_tool_run(
            conversation_id=conversation_id,
            tool_id=tool_id,
            input_json=json.dumps(arguments),
            status="running"
        )

    start = time.time()

    try:
        if tool_name == "shell":
            result = shell_tool.run(arguments.get("command", ""))
        elif tool_name == "notes":
            action = arguments.pop("action", "list")
            result = notes_tool.run(action, **arguments)
        elif tool_name == "saviynt":
            action = arguments.pop("action", "templates")
            result = saviynt_tool.run(action, **arguments)
        elif tool_name == "mac":
            action = arguments.pop("action", "")
            result = mac_tool.run(action, **arguments)
        elif tool_name == "memory":
            action = arguments.pop("action", "query")
            result = memory_tool.run(action, **arguments)
        else:
            result = {"success": False, "error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        result = {"success": False, "error": f"Tool execution error: {e}"}

    duration_ms = int((time.time() - start) * 1000)

    # Complete audit record
    if tool_run_id:
        complete_tool_run(
            tool_run_id=tool_run_id,
            status="success" if result.get("success", False) else "failed",
            output_json=json.dumps(result)[:2000],
            error_text=result.get("error"),
            duration_ms=duration_ms
        )

    return result, duration_ms, tool_run_id


def parse_tool_call(message) -> Optional[Tuple[str, Dict, str]]:
    """Parse an OpenAI tool call. Returns (tool_name, arguments, call_id)."""
    if not message.tool_calls:
        return None
    tool_call = message.tool_calls[0]
    tool_name = tool_call.function.name
    try:
        arguments = json.loads(tool_call.function.arguments)
    except json.JSONDecodeError:
        arguments = {}
    return tool_name, arguments, tool_call.id


def format_tool_result(tool_name: str, result: Dict) -> str:
    """Format tool result for display and LLM context."""
    if not result.get("success", False):
        return f"❌ [{tool_name}] Error: {result.get('error', 'Unknown error')}"

    if tool_name == "shell":
        output = result.get("output", "")
        error = result.get("error", "")
        parts = []
        if output:
            parts.append(output)
        if error:
            parts.append(f"(stderr: {error})")
        return "\n".join(parts) if parts else "(no output)"

    elif tool_name == "notes":
        if "notes" in result:
            lines = [f"Found {result['count']} note(s):"]
            for n in result["notes"]:
                tags = ", ".join(n.get("tags", []))
                tag_str = f" [{tags}]" if tags else ""
                lines.append(f"  #{n['id']}{tag_str}: {n['text']}")
            return "\n".join(lines)
        return result.get("message", json.dumps(result))

    elif tool_name == "saviynt":
        if "query" in result:
            return f"Generated query ({result.get('template', 'custom')}):\n\n{result['query']}"
        if "templates" in result:
            lines = ["Available Saviynt templates:"]
            for t in result["templates"]:
                lines.append(f"  • {t['name']}")
            return "\n".join(lines)
        if "json" in result:
            return f"{result.get('description', '')}:\n\n{json.dumps(result['json'], indent=2)}"
        return json.dumps(result, indent=2)

    elif tool_name == "mac":
        output = result.get("output", "")
        return output if output else "✓ Done"

    elif tool_name == "memory":
        if "memories" in result:
            method = result.get("method", "keyword")
            lines = [f"Found {result['count']} memories ({method}):"]
            for m in result["memories"]:
                score = f" [{m['score']:.2f}]" if m.get("score") else ""
                title = m.get("title") or m.get("text", m.get("body", ""))[:80]
                lines.append(f"  • {title}{score}")
            return "\n".join(lines)
        return result.get("message", json.dumps(result))

    return json.dumps(result, indent=2)
