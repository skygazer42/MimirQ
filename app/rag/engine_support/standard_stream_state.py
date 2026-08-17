"""Explicit runtime state shared by standard streaming phases."""

from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any


class StandardStreamState:
    """Request-local mutable state shared across semantic stream phases."""

    __slots__ = ("data", "engine", "finished", "module")

    def __init__(
        self,
        *,
        engine: Any,
        module: Any,
        payload: dict[str, Any],
    ) -> None:
        self.engine = engine
        self.module = module
        self.data = SimpleNamespace(**payload)
        self.finished = False


@dataclass(frozen=True, slots=True)
class StreamOperation:
    """One ordered standard-stream operation and its event contract."""

    callback: Callable[[StandardStreamState], Any]
    streams: bool


__all__ = ["StandardStreamState", "StreamOperation"]
