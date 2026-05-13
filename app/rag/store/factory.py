"""
LangGraph Store factory.

This is a scaffold for future LangGraph-based long-term memory. When disabled,
the graph runs without a store (default).
"""

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("rag.store.factory")

_store = None


def get_langgraph_store():
    """Return a LangGraph BaseStore instance (or None when disabled)."""
    global _store

    enabled = bool(getattr(settings, "LANGGRAPH_STORE_ENABLED", False))
    if not enabled:
        return None

    if _store is not None:
        return _store

    backend = str(getattr(settings, "LANGGRAPH_STORE_BACKEND", "memory") or "memory").strip().lower()
    if backend in {"none", "disabled"}:
        return None

    if backend == "memory":
        try:
            from langgraph.store.memory import InMemoryStore
        except ImportError as exc:
            logger.warning(
                "LangGraph store backend 'memory' unavailable: %s (hint: pip install langgraph)",
                str(exc)[:200],
            )
            return None

        _store = InMemoryStore()
        logger.info("Using LangGraph in-memory store (non-persistent)")
        return _store

    logger.warning("Unsupported LangGraph store backend '%s' (store disabled)", backend)
    return None
