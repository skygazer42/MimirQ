"""
Reranker type definitions
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence


@dataclass(frozen=True)
class RerankCandidate:
    """Rerank candidate item"""
    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RerankResult:
    """Rerank result"""
    ordered_ids: list[str]
    score_map: dict[str, float]
    items: list[dict[str, Any]] = field(default_factory=list)
    clues: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    elapsed_sec: float | None = None
    model_used: str | None = None
    provider: str | None = None


class SyncReranker(Protocol):
    """Synchronous Reranker protocol"""
    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: Any,
    ) -> RerankResult:
        ...


class AsyncReranker(Protocol):
    """Asynchronous Reranker protocol"""
    async def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: Any,
    ) -> RerankResult:
        ...
