"""
Reciprocal Rank Fusion reranker combining recall score and query similarity.
"""
from typing import Any, Dict, List

from app.parsing.sag_load.processor import DocumentProcessor
from app.rag.sag_search.config import SearchConfig
from app.storage.sag_repository import EventRepository, get_session


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

            def cosine(a, b):
                import math

                if not a or not b or len(a) != len(b):
                    return 0.0
                dot = sum(x * y for x, y in zip(a, b))
                na = math.sqrt(sum(x * x for x in a))
                nb = math.sqrt(sum(y * y for y in b))
                if na == 0 or nb == 0:
                    return 0.0
                return dot / (na * nb)

            # Rank1: recall scores
            recall_rank = sorted(event_scores.items(), key=lambda x: x[1], reverse=True)
            recall_order = {eid: idx for idx, (eid, _) in enumerate(recall_rank)}

            # Rank2: query similarity
            sim_scores = {}
            for ev in events:
                sim = cosine(query_vec, ev.content_vector or [])
                sim_scores[str(ev.id)] = sim
            sim_rank = sorted(sim_scores.items(), key=lambda x: x[1], reverse=True)
            sim_order = {eid: idx for idx, (eid, _) in enumerate(sim_rank)}

            fused = {}
            k = config.rerank.rrf_k
            for eid in event_ids:
                r1 = recall_order.get(str(eid), len(event_ids))
                r2 = sim_order.get(str(eid), len(event_ids))
                fused[str(eid)] = 1.0 / (k + r1) + 1.0 / (k + r2)

            ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)
            results = []
            for eid, score in ranked[: config.rerank.max_results]:
                ev = next((e for e in events if str(e.id) == eid), None)
                if not ev:
                    continue
                results.append(
                    {
                        "id": str(ev.id),
                        "title": ev.title,
                        "summary": ev.summary,
                        "content": ev.content,
                        "document_id": str(ev.document_id) if ev.document_id else None,
                        "chunk_id": str(ev.chunk_id) if ev.chunk_id else None,
                        "score": score,
                    }
                )

            return {
                "events": results,
                "clues": [],
                "stats": {"total_candidates": len(events), "returned": len(results)},
            }
        finally:
            session.close()
