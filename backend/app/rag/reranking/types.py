from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence


@dataclass(frozen=True)
class RerankCandidate:
    id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RerankResult:
    ordered_ids: List[str]
    score_map: Dict[str, float]
    items: List[Dict[str, Any]] = field(default_factory=list)
    clues: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    elapsed_sec: Optional[float] = None
    model_used: Optional[str] = None
    provider: Optional[str] = None


class SyncReranker(Protocol):
    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: Any,
    ) -> RerankResult:
        ...


class AsyncReranker(Protocol):
    async def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: Any,
    ) -> RerankResult:
        ...

