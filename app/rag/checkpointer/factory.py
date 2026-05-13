"""
Checkpoint saver factory module.

Provides configuration-based checkpoint saver selection.
"""

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.core.config import settings
from app.rag.checkpointer.sqlite import SqliteSaver
from app.rag.core.logging import get_logger

try:  # LangGraph 1.0.x compatibility
    from langgraph.checkpoint.memory import InMemorySaver  # type: ignore
except Exception:  # pragma: no cover
    from langgraph.checkpoint.memory import MemorySaver as InMemorySaver  # type: ignore

logger = get_logger("rag.checkpointer.factory")

# Configuration
CHECKPOINT_BACKEND = getattr(settings, "CHECKPOINT_BACKEND", "memory")
CHECKPOINT_SQLITE_PATH = getattr(settings, "CHECKPOINT_SQLITE_PATH", "./data/checkpoints.db")

# Global instance
_checkpointer: BaseCheckpointSaver | None = None


def get_checkpointer(
    backend: str | None = None,
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
