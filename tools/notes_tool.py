"""Legacy notes tool.

Kept for backward-compat and quick capture. Under the hood it uses
memory_items with memory_type='note'.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from memory.memory import store_memory, search_memories, delete_memory


def run(action: str = "list", text: str = None, query: str = None, tags: str = None, limit: int = 10, note_id: str = None) -> Dict:
    try:
        action = (action or "list").lower()

        if action in ("add", "write", "create"):
            if not text:
                return {"success": False, "error": "text is required"}
            mem_id = store_memory(body=text, memory_type="note", tags=tags, source="user")
            return {"success": True, "message": f"Note saved as {mem_id}", "id": mem_id}

        if action in ("list", "search", "find"):
            q = query if action != "list" else None
            results = search_memories(query=q, memory_type="note", tags=tags, limit=limit)
            notes = []
            for r in results:
                notes.append({
                    "id": r["memory_id"],
                    "text": r["body"],
                    "tags": (r.get("tags") or "").split(",") if r.get("tags") else [],
                    "created_at": r.get("created_at"),
                })
            return {"success": True, "count": len(notes), "notes": notes}

        if action in ("delete", "remove"):
            if not note_id:
                return {"success": False, "error": "note_id is required"}
            ok = delete_memory(note_id)
            return {"success": ok, "message": f"Note {note_id} {'deleted' if ok else 'not found'}"}

        return {"success": False, "error": f"Unknown action: {action}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


TOOL_DEF = {
    "name": "notes",
    "description": "Quick notes (legacy). Actions: add, list, search, delete. Stores into Jarvis memory as type 'note'.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add", "list", "search", "delete"], "description": "Action"},
            "text": {"type": "string", "description": "Note text (for add)"},
            "query": {"type": "string", "description": "Search query (for search)"},
            "tags": {"type": "string", "description": "Comma-separated tags"},
            "limit": {"type": "integer", "description": "Max results"},
            "note_id": {"type": "string", "description": "Note/memory id (for delete)"},
        },
        "required": ["action"],
    },
}
