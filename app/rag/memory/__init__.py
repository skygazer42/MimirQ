"""
Memory management module for RAG pipelines.

Provides:
- short_term: Message trimming and conversation summarization
- long_term: Persistent user preferences and cross-session memory
"""

from app.rag.memory.long_term import (
    BaseMemoryStore,
    InMemoryStore,
    MemoryItem,
    SqliteStore,
    UserMemory,
    get_memory_store,
    inject_user_memory_context,
    retrieve_user_memory,
    set_memory_store,
)
from app.rag.memory.short_term import (
    ShortTermMemoryManager,
    SummarizationMiddleware,
    delete_old_messages,
    summarize_messages,
    trim_messages,
)

__all__ = [
    # Short-term memory
    "ShortTermMemoryManager",
    "SummarizationMiddleware",
    "trim_messages",
    "summarize_messages",
    "delete_old_messages",
    # Long-term memory
    "MemoryItem",
    "BaseMemoryStore",
    "InMemoryStore",
    "SqliteStore",
    "UserMemory",
    "get_memory_store",
    "set_memory_store",
    "retrieve_user_memory",
    "inject_user_memory_context",
]
