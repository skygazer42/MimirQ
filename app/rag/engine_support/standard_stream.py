"""Standard streaming executor for the RAG engine."""

from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any

from app.rag.engine_support.standard_stream_evidence import EVIDENCE_OPERATIONS
from app.rag.engine_support.standard_stream_finalization import (
    FINALIZATION_OPERATIONS,
)
from app.rag.engine_support.standard_stream_generation import GENERATION_OPERATIONS
from app.rag.engine_support.standard_stream_query import QUERY_OPERATIONS
from app.rag.engine_support.standard_stream_retrieval import RETRIEVAL_OPERATIONS
from app.rag.engine_support.standard_stream_setup import SETUP_OPERATIONS
from app.rag.engine_support.standard_stream_state import StandardStreamState


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
        engine: Any,
        module: Any,
        inputs: StandardStreamInputs,
    ) -> None:
        self.engine = engine
        self.module = module
        self.inputs = inputs

    async def stream(self) -> AsyncGenerator[dict[str, Any], None]:
        runtime = StandardStreamState(
            engine=self.engine,
            module=self.module,
            payload=self.inputs.as_state(),
        )
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


__all__ = ["StandardStreamExecutor", "StandardStreamInputs"]
