"""Standard streaming executor for the RAG engine."""

import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.rag.runtime.streaming.evidence import EVIDENCE_OPERATIONS
from app.rag.runtime.streaming.finalization import FINALIZATION_OPERATIONS
from app.rag.runtime.streaming.generation import GENERATION_OPERATIONS
from app.rag.runtime.streaming.query import QUERY_OPERATIONS
from app.rag.runtime.streaming.retrieval import RETRIEVAL_OPERATIONS, start_ontology_evidence
from app.rag.runtime.streaming.setup import SETUP_OPERATIONS
from app.rag.runtime.streaming.state import StandardStreamState

logger = logging.getLogger("rag.engine")

if TYPE_CHECKING:
    from app.rag.runtime.engine import RAGEngine


@dataclass(frozen=True)
class StandardStreamInputs:
    payload: dict[str, Any]

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> "StandardStreamInputs":
        return cls(payload=dict(state))

    def as_state(self) -> dict[str, Any]:
        return dict(self.payload)


_STANDARD_OPERATIONS = (
    *SETUP_OPERATIONS,
    *QUERY_OPERATIONS,
    *RETRIEVAL_OPERATIONS,
    *EVIDENCE_OPERATIONS,
    *GENERATION_OPERATIONS,
    *FINALIZATION_OPERATIONS,
)


class StandardStreamExecutor:
    def __init__(
        self,
        *,
        engine: "RAGEngine",
        inputs: StandardStreamInputs,
    ) -> None:
        self.engine = engine
        self.inputs = inputs

    async def stream(self) -> AsyncGenerator[dict[str, Any], None]:
        runtime = StandardStreamState(
            engine=self.engine,
            payload=self.inputs.as_state(),
        )
        start_ontology_evidence(runtime)
        try:
            for operation in _STANDARD_OPERATIONS:
                if runtime.finished:
                    return
                result = operation.callback(runtime)
                if not operation.streams:
                    await result
                    continue
                async with aclosing(result) as events:
                    async for event in events:
                        yield event
        finally:
            if runtime.ontology_task is not None:
                # The worker owns a database session and must finish before the request exits.
                error = sys.exception()
                try:
                    await runtime.ontology_task
                except BaseException as cleanup_error:
                    if error is None or isinstance(error, GeneratorExit):
                        raise
                    if cleanup_error is not error:
                        error.add_note(f"Ontology worker cleanup failed: {type(cleanup_error).__name__}")
                        logger.warning("Ontology worker failed while preserving the request error", exc_info=True)


__all__ = ["StandardStreamExecutor", "StandardStreamInputs"]
