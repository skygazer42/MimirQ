"""
LangGraph Store factory.

This is a scaffold for future LangGraph-based long-term memory. When disabled,
the graph runs without a store (default).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import settings
from app.core.optional_deps import require_dependency
from app.rag.core.logging import get_logger

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore

logger = get_logger("rag.store.factory")

_store: BaseStore | None = None


def get_langgraph_store() -> BaseStore | None:
    """Return a LangGraph BaseStore instance (or None when disabled)."""
    global _store

    enabled = bool(settings.LANGGRAPH_STORE_ENABLED)
    if not enabled:
        return None

    if _store is not None:
        return _store

    backend = str(settings.LANGGRAPH_STORE_BACKEND or "memory").strip().lower()
    if backend in {"none", "disabled"}:
        return None

    if backend == "memory":
        langgraph_memory = require_dependency(
            "langgraph.store.memory",
            feature="langgraph_store",
            pip_name="langgraph",
        )
        in_memory_store_cls = getattr(langgraph_memory, "InMemoryStore", None)
        if in_memory_store_cls is None:
            raise RuntimeError("langgraph.store.memory.InMemoryStore missing (unsupported langgraph version)")

        _store = in_memory_store_cls()
        logger.info("Using LangGraph in-memory store (non-persistent)")
        return _store

    logger.warning("Unsupported LangGraph store backend '%s' (store disabled)", backend)
    return None
