"""
Placeholder Reciprocal Rank Fusion reranker.
"""
from typing import Any, Dict, List

from app.sag.modules.search.config import SearchConfig


class RerankRRFSearcher:
    def __init__(self, *args, **kwargs):
        ...

    async def rerank(self, config: SearchConfig, event_ids: List[str]) -> Dict[str, Any]:
        # Fallback: just return empty; pagerank searcher is used by default.
        return {"events": [], "clues": [], "stats": {}}

