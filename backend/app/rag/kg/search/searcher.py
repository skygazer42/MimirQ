"""
Unified entry for SAG search: recall -> expand -> rerank.
"""
from typing import Any, Dict

from app.rag.kg.search.config import SearchConfig, ReturnType
from app.rag.kg.search.recall import RecallSearcher
from app.rag.kg.search.expand import ExpandSearcher
from app.rag.reranking.kg import get_kg_reranker
from app.rag.reranking.types import RerankCandidate
from app.rag.kg.utils import get_logger

logger = get_logger("sag.search.searcher")


class SAGSearcher:
    def __init__(self):
        self.recall_searcher = RecallSearcher()
        self.expand_searcher = ExpandSearcher()

    async def search(self, config: SearchConfig) -> Dict[str, Any]:
        # recall
        recall_result = await self.recall_searcher.search(config)

        # expand (currently passthrough)
        expand_result = await self.expand_searcher.expand(config, recall_result)

        # rerank
        candidates = [RerankCandidate(id=str(eid), text="") for eid in expand_result.event_ids]
        reranker = get_kg_reranker(config.rerank.strategy)
        rerank_result = await reranker.rerank(
            query=config.query,
            candidates=candidates,
            config=config,
            event_scores=expand_result.event_scores,
            key_final=expand_result.key_final,
        )

        if config.return_type == ReturnType.EVENT:
            return {
                "events": rerank_result.items,
                "clues": (expand_result.clues or []) + (rerank_result.clues or []),
                "stats": rerank_result.stats,
                "query": {"original": config.query},
            }

        return {
            "events": rerank_result.items,
            "clues": (expand_result.clues or []) + (rerank_result.clues or []),
            "stats": rerank_result.stats,
        }
