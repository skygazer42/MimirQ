"""
Reciprocal Rank Fusion reranker combining recall score and query similarity.
"""
from typing import Any, Dict, List

from app.rag.kg.loading.processor import DocumentProcessor
from app.rag.kg.search.config import SearchConfig
from app.rag.kg.search.utils import cosine_similarity, format_events
from app.rag.kg.repository import EventRepository, get_session


class RerankRRFSearcher:
    def __init__(self, *args, **kwargs):
        self.processor = DocumentProcessor()

    async def rerank(
        self,
        config: SearchConfig,
        event_ids: List[str],
        event_scores: Dict[str, float],
    ) -> Dict[str, Any]:
        session = get_session()
        try:
            repo = EventRepository(session)
            events = repo.get_events_by_ids(event_ids)
            if not events:
                return {"events": [], "clues": [], "stats": {}}

            query_vec = await self.processor.generate_embedding(config.query)

            # Rank1: recall scores
            recall_rank = sorted(event_scores.items(), key=lambda x: x[1], reverse=True)
            recall_order = {eid: idx for idx, (eid, _) in enumerate(recall_rank)}

            # Rank2: query similarity
            sim_scores = {}
            for ev in events:
                sim = cosine_similarity(query_vec, ev.content_vector or [])
                sim_scores[str(ev.id)] = sim
            sim_rank = sorted(sim_scores.items(), key=lambda x: x[1], reverse=True)
            sim_order = {eid: idx for idx, (eid, _) in enumerate(sim_rank)}

            fused = {}
            k = config.rerank.rrf_k
            for eid in event_ids:
                r1 = recall_order.get(str(eid), len(event_ids))
                r2 = sim_order.get(str(eid), len(event_ids))
                fused[str(eid)] = 1.0 / (k + r1) + 1.0 / (k + r2)

            results = format_events(events, fused, config.rerank.max_results)

            return {
                "events": results,
                "clues": [],
                "stats": {"total_candidates": len(events), "returned": len(results)},
            }
        finally:
            session.close()
