"""
Unified entry for SAG search: recall -> expand -> rerank.
"""
from typing import Any, Dict

from app.rag.sag_search.config import RerankStrategy, SearchConfig, ReturnType
from app.rag.sag_search.recall import RecallSearcher
from app.rag.sag_search.expand import ExpandSearcher
from app.rag.sag_search.ranking.pagerank import RerankPageRankSearcher
from app.rag.sag_search.ranking.rrf import RerankRRFSearcher
from app.core.sag_utils import get_logger

logger = get_logger("sag.search.searcher")


class SAGSearcher:
    def __init__(self):
        self.recall_searcher = RecallSearcher()
        self.expand_searcher = ExpandSearcher()
        self.rerank_pagerank = RerankPageRankSearcher()
        self.rerank_rrf = RerankRRFSearcher()

    async def search(self, config: SearchConfig) -> Dict[str, Any]:
        # recall
        recall_result = await self.recall_searcher.search(config)

        # expand (currently passthrough)
        expand_result = await self.expand_searcher.expand(config, recall_result)

        # rerank
        if config.rerank.strategy == RerankStrategy.PAGERANK:
            rerank_result = await self.rerank_pagerank.rerank(
                config,
                expand_result.event_ids,
                expand_result.key_final,
                expand_result.event_scores,
            )
        else:
            rerank_result = await self.rerank_rrf.rerank(
                config,
                expand_result.event_ids,
                expand_result.event_scores,
            )

        if config.return_type == ReturnType.EVENT:
            return {
                "events": rerank_result.get("events", []),
                "clues": (expand_result.clues or []) + rerank_result.get("clues", []),
                "stats": rerank_result.get("stats", {}),
                "query": {"original": config.query},
            }

        return rerank_result
