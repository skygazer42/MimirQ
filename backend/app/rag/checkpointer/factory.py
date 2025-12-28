"""
Checkpointer factory for creating checkpoint savers.

Provides configuration-based checkpointer selection.
"""

import logging
from typing import Optional
from app.rag.checkpointer.sqlite import SqliteSaver
from app.core.config import settings
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

logger = logging.getLogger(__name__)

# Configuration
CHECKPOINT_BACKEND = getattr(settings, "CHECKPOINT_BACKEND", "memory")
CHECKPOINT_SQLITE_PATH = getattr(settings, "CHECKPOINT_SQLITE_PATH", "./data/checkpoints.db")

# Global instance
_checkpointer: Optional[BaseCheckpointSaver] = None


def get_checkpointer(
    backend: Optional[str] = None,
    **kwargs,
) -> BaseCheckpointSaver:
    """
    Get or create a checkpointer instance.

    Args:
        backend: Backend type ("sqlite" or "memory")
        **kwargs: Additional configuration

    Returns:
        Checkpointer instance
    """
    global _checkpointer

    if _checkpointer is not None and backend is None:
        return _checkpointer

    backend = (backend or CHECKPOINT_BACKEND).lower().strip()

    if backend == "sqlite":
        db_path = kwargs.get("db_path", CHECKPOINT_SQLITE_PATH)
        _checkpointer = SqliteSaver(db_path=db_path)
        logger.info("Using SQLite checkpointer: %s", db_path)
    else:
        _checkpointer = InMemorySaver()
        logger.info("Using in-memory checkpointer")

    return _checkpointer


def set_checkpointer(checkpointer: BaseCheckpointSaver) -> None:
    """
    Set the global checkpointer instance.

    Args:
        checkpointer: Checkpointer to use
    """
    global _checkpointer
    _checkpointer = checkpointer


def reset_checkpointer() -> None:
    """Reset the global checkpointer instance."""
    global _checkpointer
    _checkpointer = None
