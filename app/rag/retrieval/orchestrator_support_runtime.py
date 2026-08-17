from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass
class RetrievalRuntimeState:
    """Shared state passed through the ordered retrieval phases."""

    state: dict[str, Any]
    question: str
    history_text: str


RetrievalPhase = Callable[[RetrievalRuntimeState], dict[str, Any] | None]


def run_retrieval_runtime(
    runtime: RetrievalRuntimeState,
    *,
    phases: Sequence[RetrievalPhase],
) -> dict[str, Any]:
    """Run retrieval phases in order and return the terminal phase result."""
    for phase in phases:
        result = phase(runtime)
        if result is not None:
            return result
    raise RuntimeError("retrieval runtime completed without a result")
