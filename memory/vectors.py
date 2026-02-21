"""
Jarvis v2 Vector Store
Chroma-backed semantic search for memory items.
Keeps a registry in SQLite (memory_vectors) for auditability.

Usage:
    from memory.vectors import VectorStore
    vs = VectorStore()
    vs.store("mem_abc123", "Saviynt DA table limits prevent bulk queries", 
             metadata={"memory_type": "fact", "tags": "saviynt,data-analyzer"})
    results = vs.search("Saviynt query limits", top_k=5)
"""

import os
import uuid
from typing import Dict, List, Optional
from datetime import datetime

CHROMA_AVAILABLE = False
try:
    import chromadb
    from chromadb.config import Settings
    CHROMA_AVAILABLE = True
except ImportError:
    pass

OPENAI_AVAILABLE = False
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    pass

from memory.memory import get_connection, DB_PATH

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROMA_DIR = os.path.join(BASE_DIR, "memory", "chroma_db")

# Collection names matching the architecture doc
COLLECTION_MEMORIES = "memories"
COLLECTION_SKILLS = "skills"
COLLECTION_FINANCE = "finance_research"

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536


class VectorStore:
    """
    Semantic memory layer backed by Chroma + OpenAI embeddings.
    Falls back to keyword search if Chroma/OpenAI unavailable.
    """

    def __init__(self, api_key: str = None):
        self.chroma_client = None
        self.openai_client = None
        self.collections: Dict = {}
        self._available = False

        if CHROMA_AVAILABLE:
            try:
                self.chroma_client = chromadb.PersistentClient(
                    path=CHROMA_DIR,
                    settings=Settings(anonymized_telemetry=False)
                )
                # Initialize collections
                for name in [COLLECTION_MEMORIES, COLLECTION_SKILLS, COLLECTION_FINANCE]:
                    self.collections[name] = self.chroma_client.get_or_create_collection(
                        name=name,
                        metadata={"hnsw:space": "cosine"}
                    )
                self._available = True
            except Exception as e:
                print(f"[vectors] Chroma init failed: {e}")

        if OPENAI_AVAILABLE:
            key = api_key or os.environ.get("OPENAI_API_KEY")
            if key:
                self.openai_client = OpenAI(api_key=key)

    @property
    def available(self) -> bool:
        return self._available and self.openai_client is not None

    def _embed(self, text: str) -> List[float]:
        """Get embedding from OpenAI."""
        if not self.openai_client:
            raise RuntimeError("OpenAI client not initialized")
        response = self.openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text
        )
        return response.data[0].embedding

    def store(self, memory_id: str, text: str, collection: str = COLLECTION_MEMORIES,
              metadata: Dict = None, db_path: str = None) -> Optional[str]:
        """
        Embed and store a document. Also registers in SQLite memory_vectors.
        
        Args:
            memory_id: Links to memory_items.memory_id
            text: The text to embed
            collection: Which Chroma collection
            metadata: Additional metadata for filtering
        
        Returns:
            vector_id if successful, None if unavailable
        """
        if not self.available:
            return None

        try:
            embedding = self._embed(text)
            chroma_id = f"vec_{uuid.uuid4().hex[:12]}"

            # Store in Chroma
            coll = self.collections.get(collection)
            if not coll:
                return None

            meta = metadata or {}
            meta["memory_id"] = memory_id
            meta["stored_at"] = datetime.now().isoformat()
            # Chroma metadata values must be str, int, float, or bool
            clean_meta = {k: str(v) if v is not None else "" for k, v in meta.items()}

            coll.upsert(
                ids=[chroma_id],
                embeddings=[embedding],
                documents=[text],
                metadatas=[clean_meta]
            )

            # Register in SQLite
            vector_id = f"vecr_{uuid.uuid4().hex[:12]}"
            conn = get_connection(db_path)
            conn.execute(
                """INSERT OR REPLACE INTO memory_vectors 
                   (vector_id, memory_id, provider, collection_name, 
                    embedding_model, dimension, external_ref)
                   VALUES (?,?,?,?,?,?,?)""",
                (vector_id, memory_id, "chroma", collection,
                 EMBEDDING_MODEL, EMBEDDING_DIM, chroma_id)
            )
            conn.commit()
            conn.close()

            return vector_id

        except Exception as e:
            print(f"[vectors] Store failed: {e}")
            return None

    def search(self, query: str, collection: str = COLLECTION_MEMORIES,
               top_k: int = 5, where: Dict = None) -> List[Dict]:
        """
        Semantic search across a collection.
        
        Returns:
            List of {memory_id, text, score, metadata}
        """
        if not self.available:
            return []

        try:
            embedding = self._embed(query)
            coll = self.collections.get(collection)
            if not coll:
                return []

            kwargs = {
                "query_embeddings": [embedding],
                "n_results": top_k,
            }
            if where:
                kwargs["where"] = where

            results = coll.query(**kwargs)

            output = []
            if results and results["ids"] and results["ids"][0]:
                for i, doc_id in enumerate(results["ids"][0]):
                    output.append({
                        "chroma_id": doc_id,
                        "memory_id": results["metadatas"][0][i].get("memory_id", ""),
                        "text": results["documents"][0][i] if results["documents"] else "",
                        "score": 1 - (results["distances"][0][i] if results["distances"] else 0),
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {}
                    })

            return output

        except Exception as e:
            print(f"[vectors] Search failed: {e}")
            return []

    def delete(self, memory_id: str, collection: str = COLLECTION_MEMORIES,
               db_path: str = None) -> bool:
        """Delete all vectors associated with a memory_id."""
        if not self.available:
            return False

        try:
            # Find in SQLite registry
            conn = get_connection(db_path)
            rows = conn.execute(
                "SELECT external_ref, collection_name FROM memory_vectors WHERE memory_id = ?",
                (memory_id,)
            ).fetchall()

            for row in rows:
                coll = self.collections.get(row["collection_name"])
                if coll:
                    try:
                        coll.delete(ids=[row["external_ref"]])
                    except Exception:
                        pass

            conn.execute("DELETE FROM memory_vectors WHERE memory_id = ?", (memory_id,))
            conn.commit()
            conn.close()
            return True

        except Exception as e:
            print(f"[vectors] Delete failed: {e}")
            return False

    def stats(self) -> Dict:
        """Get vector store statistics."""
        if not self.available:
            return {"available": False, "reason": "Chroma or OpenAI not configured"}

        stats = {"available": True, "collections": {}}
        for name, coll in self.collections.items():
            try:
                stats["collections"][name] = {"count": coll.count()}
            except Exception:
                stats["collections"][name] = {"count": 0}
        return stats
