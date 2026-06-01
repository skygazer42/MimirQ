"""
Checkpointer module for workflow state persistence.

Provides:
- SqliteSaver: SQLite-based persistent checkpointing
- MemorySaver: In-memory checkpointing (non-persistent, for dev)
- TimeTravel: Time travel debugging for replaying and forking
"""

from app.rag.checkpointer.factory import get_checkpointer
from app.rag.checkpointer.sqlite import SqliteSaver
from app.rag.core.logging import get_logger

logger = get_logger(__name__)

try:  # LangGraph 1.0.x compatibility
    from langgraph.checkpoint.memory import InMemorySaver as MemorySaver  # type: ignore
except Exception:  # pragma: no cover
    from langgraph.checkpoint.memory import MemorySaver  # type: ignore

__all__ = ["SqliteSaver", "MemorySaver", "get_checkpointer"]

# Optional: time-travel utilities depend on LangGraph graph internals (version-sensitive).
try:  # pragma: no cover
    from app.rag.checkpointer.time_travel import (  # noqa: F401
        CheckpointInfo,
        ForkResult,
        TimeTravel,
        get_time_travel,
    )

    __all__.extend(["TimeTravel", "CheckpointInfo", "ForkResult", "get_time_travel"])
except Exception as exc:
    logger.debug("Ignoring optional time-travel checkpointer import failure: %s", exc)
