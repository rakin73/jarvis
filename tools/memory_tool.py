"""
Jarvis Memory Tool
LLM-callable tool for storing, querying, pinning, and deleting memories.
Integrates both SQLite and Chroma vector search.
"""

from typing import Dict
from memory.memory import (
    store_memory, search_memories, get_memory, update_memory,
    pin_memory, delete_memory, get_memory_stats
)

# Lazy-loaded vector store (initialized on first use)
_vector_store = None


def _get_vectors():
    global _vector_store
    if _vector_store is None:
        try:
            from memory.vectors import VectorStore
            _vector_store = VectorStore()
        except Exception:
            _vector_store = False  # Mark as unavailable
    return _vector_store if _vector_store else None


def run(action: str, **kwargs) -> Dict:
    """
    Memory management tool.
    
    Actions:
        - write: Store a new memory (body, title, memory_type, tags, importance, pin)
        - query: Search memories by text/tags/type (query, memory_type, tags, min_importance)
        - semantic: Semantic search via embeddings (query, top_k)
        - pin: Pin a memory to prevent expiration (memory_id)
        - update: Update a memory (memory_id, + any fields to change)
        - delete: Delete a memory (memory_id)
        - stats: Get memory statistics
    """
    try:
        if action == "write":
            body = kwargs.get("body", "")
            if not body:
                return {"success": False, "error": "body is required"}

            mem_id = store_memory(
                body=body,
                memory_type=kwargs.get("memory_type", "note"),
                title=kwargs.get("title"),
                tags=kwargs.get("tags"),
                importance=kwargs.get("importance", 3),
                pin=kwargs.get("pin", False),
                source=kwargs.get("source", "assistant"),
                source_ref=kwargs.get("source_ref"),
                expires_at=kwargs.get("expires_at"),
            )

            # Also embed in vector store if available
            vs = _get_vectors()
            if vs:
                text_to_embed = f"{kwargs.get('title', '')} {body}".strip()
                meta = {
                    "memory_type": kwargs.get("memory_type", "note"),
                    "tags": kwargs.get("tags", ""),
                    "importance": str(kwargs.get("importance", 3)),
                }
                vs.store(mem_id, text_to_embed, metadata=meta)

            return {"success": True, "memory_id": mem_id, "message": f"Memory stored: {mem_id}"}

        elif action == "query":
            results = search_memories(
                query=kwargs.get("query"),
                memory_type=kwargs.get("memory_type"),
                tags=kwargs.get("tags"),
                min_importance=kwargs.get("min_importance"),
                limit=kwargs.get("limit", 10),
            )
            return {
                "success": True,
                "count": len(results),
                "memories": [
                    {
                        "memory_id": m["memory_id"],
                        "type": m["memory_type"],
                        "title": m.get("title"),
                        "body": m["body"][:300] + ("..." if len(m["body"]) > 300 else ""),
                        "tags": m.get("tags"),
                        "importance": m["importance"],
                        "pinned": bool(m["pin_status"]),
                        "created_at": m["created_at"],
                    }
                    for m in results
                ]
            }

        elif action == "semantic":
            query = kwargs.get("query", "")
            if not query:
                return {"success": False, "error": "query is required for semantic search"}

            vs = _get_vectors()
            if not vs:
                # Fallback to keyword search
                results = search_memories(query=query, limit=kwargs.get("top_k", 5))
                return {
                    "success": True,
                    "method": "keyword_fallback",
                    "count": len(results),
                    "memories": [
                        {
                            "memory_id": m["memory_id"],
                            "type": m["memory_type"],
                            "title": m.get("title"),
                            "body": m["body"][:300],
                            "score": None,
                        }
                        for m in results
                    ]
                }

            vec_results = vs.search(
                query=query,
                top_k=kwargs.get("top_k", 5),
            )
            return {
                "success": True,
                "method": "semantic",
                "count": len(vec_results),
                "memories": [
                    {
                        "memory_id": r["memory_id"],
                        "text": r["text"][:300],
                        "score": round(r["score"], 3),
                        "metadata": r["metadata"],
                    }
                    for r in vec_results
                ]
            }

        elif action == "pin":
            mem_id = kwargs.get("memory_id", "")
            if not mem_id:
                return {"success": False, "error": "memory_id is required"}
            pinned = pin_memory(mem_id)
            return {"success": pinned, "message": f"Memory {mem_id} {'pinned' if pinned else 'not found'}"}

        elif action == "update":
            mem_id = kwargs.get("memory_id", "")
            if not mem_id:
                return {"success": False, "error": "memory_id is required"}
            updated = update_memory(mem_id, **{k: v for k, v in kwargs.items() if k != "memory_id"})
            return {"success": updated, "message": f"Memory {mem_id} {'updated' if updated else 'not found or no changes'}"}

        elif action == "delete":
            mem_id = kwargs.get("memory_id", "")
            if not mem_id:
                return {"success": False, "error": "memory_id is required"}
            # Delete from vector store too
            vs = _get_vectors()
            if vs:
                vs.delete(mem_id)
            deleted = delete_memory(mem_id)
            return {"success": deleted, "message": f"Memory {mem_id} {'deleted' if deleted else 'not found'}"}

        elif action == "stats":
            stats = get_memory_stats()
            vs = _get_vectors()
            vec_stats = vs.stats() if vs else {"available": False}
            return {"success": True, "sqlite": stats, "vectors": vec_stats}

        else:
            return {"success": False, "error": f"Unknown action: {action}. Use: write, query, semantic, pin, update, delete, stats"}

    except Exception as e:
        return {"success": False, "error": str(e)}


TOOL_DEF = {
    "name": "memory",
    "description": "Manage Jarvis's long-term memory. Actions: write (store fact/note/preference/runbook), query (keyword search by text/type/tags/importance), semantic (AI-powered similarity search), pin (make permanent), update (change fields), delete (remove), stats (overview).",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["write", "query", "semantic", "pin", "update", "delete", "stats"],
                "description": "Action to perform"
            },
            "body": {"type": "string", "description": "Memory content (for write)"},
            "title": {"type": "string", "description": "Short title (for write/update)"},
            "memory_type": {
                "type": "string",
                "enum": ["fact", "preference", "skill", "note", "web_summary", "runbook", "contact", "finance_rule"],
                "description": "Type of memory"
            },
            "tags": {"type": "string", "description": "Comma-separated tags"},
            "importance": {"type": "integer", "description": "1-5 importance level"},
            "pin": {"type": "boolean", "description": "Pin to prevent expiration"},
            "query": {"type": "string", "description": "Search text (for query/semantic)"},
            "memory_id": {"type": "string", "description": "Memory ID (for pin/update/delete)"},
            "min_importance": {"type": "integer", "description": "Min importance filter (for query)"},
            "top_k": {"type": "integer", "description": "Number of results (for semantic)"},
            "source": {"type": "string", "description": "Source: user, assistant, web, import"},
            "source_ref": {"type": "string", "description": "URL, file path, or reference"},
            "expires_at": {"type": "string", "description": "ISO datetime for expiration"},
        },
        "required": ["action"]
    }
}
