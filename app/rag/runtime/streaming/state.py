"""Explicit runtime state shared by standard streaming phases."""

from asyncio import Task
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.rag.runtime.engine import RAGEngine


class StandardStreamState:
    """Request-local mutable state shared across semantic stream phases."""

    __slots__ = ("data", "engine", "finished", "ontology_task")

    def __init__(
        self,
        *,
        engine: "RAGEngine",
        payload: dict[str, Any],
    ) -> None:
        self.engine = engine
        self.data = SimpleNamespace(
            **{
                "ontology_enabled": False,
                "ontology_context": {},
                "ontology_docs": [],
                "ontology_metrics": {},
                "ontology_action": None,
                **payload,
            }
        )
        self.finished = False
        self.ontology_task: Task | None = None


@dataclass(frozen=True, slots=True)
class StreamOperation:
    """One ordered standard-stream operation and its event contract."""

    callback: Callable[[StandardStreamState], Any]
    streams: bool


__all__ = ["StandardStreamState", "StreamOperation"]
