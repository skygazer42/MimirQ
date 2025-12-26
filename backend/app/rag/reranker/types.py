"""
Reranker 类型定义
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence


@dataclass(frozen=True)
class RerankCandidate:
    """重排候选项"""
    id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RerankResult:
    """重排结果"""
    ordered_ids: List[str]
    score_map: Dict[str, float]
    items: List[Dict[str, Any]] = field(default_factory=list)
    clues: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    elapsed_sec: Optional[float] = None
    model_used: Optional[str] = None
    provider: Optional[str] = None


class SyncReranker(Protocol):
    """同步 Reranker 协议"""
    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: Any,
    ) -> RerankResult:
        ...


class AsyncReranker(Protocol):
    """异步 Reranker 协议"""
    async def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: Any,
    ) -> RerankResult:
        ...
