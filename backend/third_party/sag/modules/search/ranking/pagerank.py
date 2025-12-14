"""
PageRank-style rerank combining query similarity and entity co-occurrence graph.
"""
from typing import Any, Dict, List, Tuple

from app.core.config import settings
from third_party.sag.modules.load.processor import DocumentProcessor
from third_party.sag.modules.search.config import SearchConfig
from third_party.sag.storage import EventRepository, get_session
from third_party.sag.utils import get_logger

logger = get_logger("sag.search.rerank.pagerank")


class RerankPageRankSearcher:
    def __init__(self):
        self.processor = DocumentProcessor()

    async def rerank(
        self,
        config: SearchConfig,
        event_ids: List[str],
        key_final: List[Dict[str, Any]],
        event_scores: Dict[str, float],
    ) -> Dict[str, Any]:
        session = get_session()
        try:
            repo = EventRepository(session)
            events = repo.get_events_by_ids(event_ids)
            if not events:
                return {"events": [], "clues": [], "stats": {}}

            query_vec = await self.processor.generate_embedding(config.query)
            key_weight_map = {k.get("entity_id"): k.get("weight", 0.0) for k in key_final}

            # prepare adjacency via shared entities
            assoc_map = repo.get_entities_for_events(event_ids)

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

            base_scores: Dict[str, float] = {**event_scores}
            for ev in events:
                sim = cosine(query_vec, ev.content_vector or [])
                ents = assoc_map.get(str(ev.id), [])
                boost = sum(key_weight_map.get(str(e.id), 0.0) for e in ents)
                # merge recall score if present
                recall_score = event_scores.get(str(ev.id), 0.0)
                base_scores[str(ev.id)] = 0.5 * recall_score + 0.3 * sim + 0.2 * boost

            graph: Dict[str, Dict[str, float]] = {str(ev.id): {} for ev in events}
            # build edges if share entities
            for i, ev in enumerate(events):
                ents_i = {str(e.id) for e in assoc_map.get(str(ev.id), [])}
                for j in range(i + 1, len(events)):
                    ev2 = events[j]
                    ents_j = {str(e.id) for e in assoc_map.get(str(ev2.id), [])}
                    shared = ents_i & ents_j
                    if not shared:
                        continue
                    w = sum(key_weight_map.get(eid, 0.1) for eid in shared)
                    graph[str(ev.id)][str(ev2.id)] = w
                    graph[str(ev2.id)][str(ev.id)] = w

            scores = self._pagerank(
                graph,
                damping=config.rerank.pagerank_damping_factor,
                max_iter=config.rerank.pagerank_max_iterations,
                base_scores=base_scores,
            )

            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
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

    def _pagerank(
        self,
        graph: Dict[str, Dict[str, float]],
        damping: float,
        max_iter: int,
        base_scores: Dict[str, float],
    ) -> Dict[str, float]:
        nodes = list(graph.keys())
        if not nodes:
            return {}
        scores = {n: 1.0 for n in nodes}
        for _ in range(max_iter):
            new_scores = {}
            for n in nodes:
                incoming = 0.0
                for m, edges in graph.items():
                    w = edges.get(n, 0.0)
                    if w == 0:
                        continue
                    out_sum = sum(edges.values()) or 1.0
                    incoming += scores[m] * (w / out_sum)
                new_scores[n] = (1 - damping) * base_scores.get(n, 0.0) + damping * incoming
            scores = new_scores
        return scores
