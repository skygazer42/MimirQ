from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from app.rag.kg.search.config import RerankStrategy, SearchConfig
from app.rag.kg.search.ranking.pagerank import RerankPageRankSearcher
from app.rag.kg.search.ranking.rrf import RerankRRFSearcher
from app.rag.reranker.base import BaseReranker
from app.rag.reranker.types import RerankCandidate, RerankResult


class KGReranker(BaseReranker):
    """知识图谱重排器：基于图算法（PageRank/RRF）的重排"""
    
    def __init__(self, strategy: RerankStrategy):
        self.strategy = strategy
        self._rrf = RerankRRFSearcher()
        self._pagerank = RerankPageRankSearcher()

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: Any,
    ) -> RerankResult:
        """
        同步重排接口（KG Reranker 仅支持异步）
        
        注意：KG Reranker 是异步的，请使用 arerank_kg() 方法。
        """
        raise NotImplementedError(
            "KGReranker only supports async operations. "
            "Please use arerank_kg() method instead."
        )

    async def arerank_kg(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        *,
        config: SearchConfig,
        event_scores: Dict[str, float],
        key_final: Optional[List[Dict[str, Any]]] = None,
    ) -> RerankResult:
        event_ids = [c.id for c in candidates if c.id]
        if not event_ids:
            return RerankResult(ordered_ids=[], score_map={})

        if self.strategy == RerankStrategy.PAGERANK:
            result = await self._pagerank.rerank(
                config,
                event_ids,
                key_final or [],
                event_scores,
            )
            provider = "pagerank"
        else:
            result = await self._rrf.rerank(
                config,
                event_ids,
                event_scores,
            )
            provider = "rrf"

        items = list(result.get("events", []))
        score_map = {
            str(item.get("id")): float(item.get("score", 0.0) or 0.0)
            for item in items
            if item.get("id") is not None
        }
        ordered_ids = [str(item.get("id")) for item in items if item.get("id") is not None]

        return RerankResult(
            ordered_ids=ordered_ids,
            score_map=score_map,
            items=items,
            clues=list(result.get("clues", []) or []),
            stats=dict(result.get("stats", {}) or {}),
            provider=provider,
        )


_kg_reranker_cache: Dict[str, KGReranker] = {}


def get_kg_reranker(strategy: RerankStrategy) -> KGReranker:
    key = str(strategy)
    cached = _kg_reranker_cache.get(key)
    if cached is not None:
        return cached
    reranker = KGReranker(strategy)
    _kg_reranker_cache[key] = reranker
    return reranker

