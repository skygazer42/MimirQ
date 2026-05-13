"""
Long-term memory system for RAG pipelines.

Provides persistent storage for user preferences, facts, and
cross-session memory retrieval.

Features:
- InMemoryStore: Fast in-memory storage (non-persistent)
- SqliteStore: SQLite-based persistent storage
- UserMemory: User preference and fact storage
- Cross-session memory retrieval
"""


import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("rag.memory.long_term")


# Configuration
LONG_TERM_MEMORY_ENABLED = getattr(settings, "LONG_TERM_MEMORY_ENABLED", False)
MEMORY_STORE_TYPE = getattr(settings, "MEMORY_STORE_TYPE", "memory")
MEMORY_SQLITE_PATH = getattr(settings, "MEMORY_SQLITE_PATH", "./data/memory.db")
LONG_TERM_MEMORY_TOP_K = getattr(settings, "LONG_TERM_MEMORY_TOP_K", 3)
LONG_TERM_MEMORY_MIN_LEN = getattr(settings, "LONG_TERM_MEMORY_MIN_LEN", 20)


class MemoryItem:
    """
    Represents a single memory item.

    Attributes:
        id: Unique identifier
        namespace: Memory namespace (e.g., "user:123", "tenant:456")
        key: Memory key
        value: Memory value (any JSON-serializable data)
        memory_type: Type of memory (fact, preference, context, etc.)
        metadata: Additional metadata
        created_at: Creation timestamp
        updated_at: Last update timestamp
        expires_at: Optional expiration timestamp
    """

    def __init__(
        self,
        id: str | None = None,
        namespace: str = "default",
        key: str = "",
        value: Any = None,
        memory_type: str = "fact",
        metadata: dict[str, Any] | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        expires_at: datetime | None = None,
    ):
        self.id = id or str(uuid4())
        self.namespace = namespace
        self.key = key
        self.value = value
        self.memory_type = memory_type
        self.metadata = metadata or {}
        self.created_at = created_at or datetime.now(UTC).replace(tzinfo=None)
        self.updated_at = updated_at or self.created_at
        self.expires_at = expires_at

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "namespace": self.namespace,
            "key": self.key,
            "value": self.value,
            "memory_type": self.memory_type,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryItem":
        """Create from dictionary."""
        def parse_datetime(value):
            if value is None:
                return None
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(value)

        return cls(
            id=data.get("id"),
            namespace=data.get("namespace", "default"),
            key=data.get("key", ""),
            value=data.get("value"),
            memory_type=data.get("memory_type", "fact"),
            metadata=data.get("metadata"),
            created_at=parse_datetime(data.get("created_at")),
            updated_at=parse_datetime(data.get("updated_at")),
            expires_at=parse_datetime(data.get("expires_at")),
        )


class BaseMemoryStore(ABC):
    """
    Abstract base class for memory stores.

    All memory stores must implement these methods for
    storing and retrieving long-term memory.
    """

    @abstractmethod
    def put(self, namespace: str, key: str, value: Any, **kwargs) -> MemoryItem:
        """
        Store a memory item.

        Args:
            namespace: Memory namespace
            key: Memory key
            value: Value to store
            **kwargs: Additional options (memory_type, metadata, expires_at)

        Returns:
            Stored MemoryItem
        """
        pass

    @abstractmethod
    def get(self, namespace: str, key: str) -> MemoryItem | None:
        """
        Retrieve a memory item by key.

        Args:
            namespace: Memory namespace
            key: Memory key

        Returns:
            MemoryItem if found, None otherwise
        """
        pass

    @abstractmethod
    def search(
        self,
        namespace: str,
        query: str | None = None,
        memory_type: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """
        Search memory items.

        Args:
            namespace: Memory namespace
            query: Optional search query
            memory_type: Optional filter by memory type
            limit: Maximum results

        Returns:
            List of matching MemoryItems
        """
        pass

    @abstractmethod
    def delete(self, namespace: str, key: str) -> bool:
        """
        Delete a memory item.

        Args:
            namespace: Memory namespace
            key: Memory key

        Returns:
            True if deleted, False otherwise
        """
        pass

    @abstractmethod
    def list(self, namespace: str, limit: int = 100) -> list[MemoryItem]:
        """
        List all memory items in a namespace.

        Args:
            namespace: Memory namespace
            limit: Maximum results

        Returns:
            List of MemoryItems
        """
        pass

    @abstractmethod
    def clear(self, namespace: str) -> int:
        """
        Clear all memory items in a namespace.

        Args:
            namespace: Memory namespace

        Returns:
            Number of items cleared
        """
        pass


class InMemoryStore(BaseMemoryStore):
    """
    In-memory implementation of memory store.

    Fast but non-persistent - data is lost on restart.
    Suitable for development and testing.
    """

    def __init__(self):
        self._store: dict[str, dict[str, MemoryItem]] = {}
        self._lock = threading.RLock()

    def put(self, namespace: str, key: str, value: Any, **kwargs) -> MemoryItem:
        with self._lock:
            if namespace not in self._store:
                self._store[namespace] = {}

            existing = self._store[namespace].get(key)
            now = datetime.now(UTC).replace(tzinfo=None)

            item = MemoryItem(
                id=existing.id if existing else None,
                namespace=namespace,
                key=key,
                value=value,
                memory_type=kwargs.get("memory_type", "fact"),
                metadata=kwargs.get("metadata"),
                created_at=existing.created_at if existing else now,
                updated_at=now,
                expires_at=kwargs.get("expires_at"),
            )

            self._store[namespace][key] = item
            return item

    def get(self, namespace: str, key: str) -> MemoryItem | None:
        with self._lock:
            ns_store = self._store.get(namespace, {})
            item = ns_store.get(key)

            if item and item.expires_at and item.expires_at < datetime.now(UTC).replace(tzinfo=None):
                # Item has expired
                del ns_store[key]
                return None

            return item

    def search(
        self,
        namespace: str,
        query: str | None = None,
        memory_type: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        with self._lock:
            ns_store = self._store.get(namespace, {})
            results = []
            now = datetime.now(UTC).replace(tzinfo=None)

            for item in ns_store.values():
                # Skip expired items
                if item.expires_at and item.expires_at < now:
                    continue

                # Filter by memory type
                if memory_type and item.memory_type != memory_type:
                    continue

                # Simple text search in key and value
                if query:
                    query_lower = query.lower()
                    key_match = query_lower in item.key.lower()
                    value_str = json.dumps(item.value) if not isinstance(item.value, str) else item.value
                    value_match = query_lower in value_str.lower()
                    if not (key_match or value_match):
                        continue

                results.append(item)

            # Sort by updated_at descending
            results.sort(key=lambda x: x.updated_at or datetime.min, reverse=True)
            return results[:limit]

    def delete(self, namespace: str, key: str) -> bool:
        with self._lock:
            ns_store = self._store.get(namespace, {})
            if key in ns_store:
                del ns_store[key]
                return True
            return False

    def list(self, namespace: str, limit: int = 100) -> list[MemoryItem]:
        with self._lock:
            ns_store = self._store.get(namespace, {})
            now = datetime.now(UTC).replace(tzinfo=None)

            # Filter out expired items
            items = [
                item for item in ns_store.values()
                if not (item.expires_at and item.expires_at < now)
            ]

            items.sort(key=lambda x: x.updated_at or datetime.min, reverse=True)
            return items[:limit]

    def clear(self, namespace: str) -> int:
        with self._lock:
            ns_store = self._store.get(namespace, {})
            count = len(ns_store)
            self._store[namespace] = {}
            return count


class SqliteStore(BaseMemoryStore):
    """
    SQLite-based persistent memory store.

    Stores memory items in a SQLite database for persistence
    across application restarts.
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or MEMORY_SQLITE_PATH
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._local.conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                isolation_level=None,
            )
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self):
        """Initialize database schema."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_items (
                id TEXT PRIMARY KEY,
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                memory_type TEXT DEFAULT 'fact',
                metadata TEXT,
                created_at TEXT,
                updated_at TEXT,
                expires_at TEXT,
                UNIQUE(namespace, key)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_namespace
            ON memory_items(namespace)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_type
            ON memory_items(namespace, memory_type)
        """)

    def put(self, namespace: str, key: str, value: Any, **kwargs) -> MemoryItem:
        conn = self._get_conn()
        now = datetime.now(UTC).replace(tzinfo=None)

        # Check for existing item
        cursor = conn.execute(
            "SELECT id, created_at FROM memory_items WHERE namespace = ? AND key = ?",
            (namespace, key)
        )
        existing = cursor.fetchone()

        item = MemoryItem(
            id=existing["id"] if existing else str(uuid4()),
            namespace=namespace,
            key=key,
            value=value,
            memory_type=kwargs.get("memory_type", "fact"),
            metadata=kwargs.get("metadata"),
            created_at=datetime.fromisoformat(existing["created_at"]) if existing else now,
            updated_at=now,
            expires_at=kwargs.get("expires_at"),
        )

        conn.execute("""
            INSERT OR REPLACE INTO memory_items
            (id, namespace, key, value, memory_type, metadata, created_at, updated_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item.id,
            item.namespace,
            item.key,
            json.dumps(item.value),
            item.memory_type,
            json.dumps(item.metadata) if item.metadata else None,
            item.created_at.isoformat() if item.created_at else None,
            item.updated_at.isoformat() if item.updated_at else None,
            item.expires_at.isoformat() if item.expires_at else None,
        ))

        return item

    def _row_to_item(self, row: sqlite3.Row) -> MemoryItem:
        """Convert database row to MemoryItem."""
        return MemoryItem(
            id=row["id"],
            namespace=row["namespace"],
            key=row["key"],
            value=json.loads(row["value"]) if row["value"] else None,
            memory_type=row["memory_type"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else None,
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
        )

    def get(self, namespace: str, key: str) -> MemoryItem | None:
        conn = self._get_conn()
        now = datetime.now(UTC).replace(tzinfo=None).isoformat()

        cursor = conn.execute("""
            SELECT * FROM memory_items
            WHERE namespace = ? AND key = ?
            AND (expires_at IS NULL OR expires_at > ?)
        """, (namespace, key, now))

        row = cursor.fetchone()
        if row:
            return self._row_to_item(row)
        return None

    def search(
        self,
        namespace: str,
        query: str | None = None,
        memory_type: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        conn = self._get_conn()
        now = datetime.now(UTC).replace(tzinfo=None).isoformat()

        sql = """
            SELECT * FROM memory_items
            WHERE namespace = ?
            AND (expires_at IS NULL OR expires_at > ?)
        """
        params: list[Any] = [namespace, now]

        if memory_type:
            sql += " AND memory_type = ?"
            params.append(memory_type)

        if query:
            sql += " AND (key LIKE ? OR value LIKE ?)"
            like_query = f"%{query}%"
            params.extend([like_query, like_query])

        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(sql, params)
        return [self._row_to_item(row) for row in cursor.fetchall()]

    def delete(self, namespace: str, key: str) -> bool:
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM memory_items WHERE namespace = ? AND key = ?",
            (namespace, key)
        )
        return cursor.rowcount > 0

    def list(self, namespace: str, limit: int = 100) -> list[MemoryItem]:
        conn = self._get_conn()
        now = datetime.now(UTC).replace(tzinfo=None).isoformat()

        cursor = conn.execute("""
            SELECT * FROM memory_items
            WHERE namespace = ?
            AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY updated_at DESC
            LIMIT ?
        """, (namespace, now, limit))

        return [self._row_to_item(row) for row in cursor.fetchall()]

    def clear(self, namespace: str) -> int:
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM memory_items WHERE namespace = ?",
            (namespace,)
        )
        return cursor.rowcount

    def cleanup_expired(self) -> int:
        """Remove all expired items."""
        conn = self._get_conn()
        now = datetime.now(UTC).replace(tzinfo=None).isoformat()
        cursor = conn.execute(
            "DELETE FROM memory_items WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,)
        )
        return cursor.rowcount


class UserMemory:
    """
    High-level interface for managing user-specific memory.

    Provides convenient methods for storing and retrieving:
    - User preferences (language, style, topics)
    - User facts (name, role, interests)
    - Conversation context
    """

    def __init__(
        self,
        user_id: str,
        tenant_id: str | None = None,
        store: BaseMemoryStore | None = None,
    ):
        """
        Initialize user memory.

        Args:
            user_id: User identifier
            tenant_id: Optional tenant identifier
            store: Memory store (uses default if not provided)
        """
        self.user_id = user_id
        self.tenant_id = tenant_id or settings.DEFAULT_TENANT_ID
        self.store = store or get_memory_store()
        self._namespace = f"user:{self.tenant_id}:{self.user_id}"

    def set_preference(self, key: str, value: Any, **kwargs) -> MemoryItem:
        """Set a user preference."""
        return self.store.put(
            self._namespace,
            f"pref:{key}",
            value,
            memory_type="preference",
            **kwargs
        )

    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a user preference."""
        item = self.store.get(self._namespace, f"pref:{key}")
        return item.value if item else default

    def set_fact(self, key: str, value: Any, **kwargs) -> MemoryItem:
        """Store a user fact."""
        return self.store.put(
            self._namespace,
            f"fact:{key}",
            value,
            memory_type="fact",
            **kwargs
        )

    def get_fact(self, key: str, default: Any = None) -> Any:
        """Get a user fact."""
        item = self.store.get(self._namespace, f"fact:{key}")
        return item.value if item else default

    def add_context(self, key: str, value: Any, **kwargs) -> MemoryItem:
        """Add conversation context."""
        return self.store.put(
            self._namespace,
            f"ctx:{key}",
            value,
            memory_type="context",
            **kwargs
        )

    def get_context(self, key: str, default: Any = None) -> Any:
        """Get conversation context."""
        item = self.store.get(self._namespace, f"ctx:{key}")
        return item.value if item else default

    def search_memory(
        self,
        query: str | None = None,
        memory_type: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """Search user memory."""
        return self.store.search(
            self._namespace,
            query=query,
            memory_type=memory_type,
            limit=limit,
        )

    def get_all_preferences(self) -> dict[str, Any]:
        """Get all user preferences as a dictionary."""
        items = self.store.search(
            self._namespace,
            memory_type="preference",
            limit=100,
        )
        return {
            item.key.replace("pref:", ""): item.value
            for item in items
        }

    def get_all_facts(self) -> dict[str, Any]:
        """Get all user facts as a dictionary."""
        items = self.store.search(
            self._namespace,
            memory_type="fact",
            limit=100,
        )
        return {
            item.key.replace("fact:", ""): item.value
            for item in items
        }

    def clear_all(self) -> int:
        """Clear all user memory."""
        return self.store.clear(self._namespace)

    def to_context_string(self) -> str:
        """
        Generate a context string for injection into prompts.

        Returns:
            Formatted string with user preferences and facts
        """
        preferences = self.get_all_preferences()
        facts = self.get_all_facts()

        parts = []

        if facts:
            fact_lines = [f"- {k}: {v}" for k, v in facts.items()]
            parts.append("User information:\n" + "\n".join(fact_lines))

        if preferences:
            pref_lines = [f"- {k}: {v}" for k, v in preferences.items()]
            parts.append("User preferences:\n" + "\n".join(pref_lines))

        return "\n\n".join(parts)


# Global store instance
_memory_store: BaseMemoryStore | None = None


def get_memory_store() -> BaseMemoryStore:
    """
    Get the configured memory store instance.

    Returns:
        BaseMemoryStore instance
    """
    global _memory_store

    if _memory_store is None:
        store_type = MEMORY_STORE_TYPE.lower()

        if store_type == "sqlite":
            _memory_store = SqliteStore(MEMORY_SQLITE_PATH)
            logger.info("Using SQLite memory store: %s", MEMORY_SQLITE_PATH)
        else:
            _memory_store = InMemoryStore()
            logger.info("Using in-memory store (non-persistent)")

    return _memory_store


def set_memory_store(store: BaseMemoryStore):
    """
    Set the memory store instance (for testing).

    Args:
        store: Memory store to use
    """
    global _memory_store
    _memory_store = store


# Convenience functions for cross-session memory retrieval


def retrieve_user_memory(
    user_id: str,
    query: str,
    tenant_id: str | None = None,
    top_k: int = LONG_TERM_MEMORY_TOP_K,
) -> list[dict[str, Any]]:
    """
    Retrieve relevant user memory for a query.

    Args:
        user_id: User identifier
        query: Search query
        tenant_id: Optional tenant identifier
        top_k: Maximum results

    Returns:
        List of relevant memory items as dictionaries
    """
    if not LONG_TERM_MEMORY_ENABLED:
        return []

    user_memory = UserMemory(user_id, tenant_id)
    items = user_memory.search_memory(query=query, limit=top_k)

    return [item.to_dict() for item in items]


def inject_user_memory_context(
    state: dict[str, Any],
    user_id_key: str = "user_id",
    tenant_id_key: str = "tenant_id",
    context_key: str = "user_context",
) -> dict[str, Any]:
    """
    Inject user memory context into state.

    This function can be used as a middleware hook to automatically
    inject user preferences and facts into the RAG pipeline state.

    Args:
        state: Current state
        user_id_key: State key for user ID
        tenant_id_key: State key for tenant ID
        context_key: State key to store context

    Returns:
        Updated state with user context
    """
    if not LONG_TERM_MEMORY_ENABLED:
        return state

    user_id = state.get(user_id_key)
    if not user_id:
        return state

    tenant_id = state.get(tenant_id_key)
    user_memory = UserMemory(str(user_id), str(tenant_id) if tenant_id else None)

    context = user_memory.to_context_string()
    if context:
        new_state = dict(state)
        new_state[context_key] = context
        return new_state

    return state
