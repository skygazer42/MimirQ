"""
PageRank-style rerank combining query similarity and entity co-occurrence graph.
"""
from typing import Any, Dict, List

from app.rag.kg.loading.processor import DocumentProcessor
from app.rag.kg.repository import EventRepository, get_session
from app.rag.kg.search.config import SearchConfig
from app.rag.kg.search.utils import cosine_similarity, format_events


class RerankPageRankSearcher:
    def __init__(self):
        self.processor = DocumentProcessor()

    async def rerank(
        self,
        config: SearchConfig,
        event_ids: List[str],
        key_final: List[Dict[str, Any]],
        event_scores: Dict[str, float],
        *,
        query_vector: List[float] | None = None,
    ) -> Dict[str, Any]:
        session = get_session()
        try:
            repo = EventRepository(session)
            events = repo.get_events_by_ids(
                event_ids,
                tenant_id=config.tenant_id,
                document_ids=config.document_ids,
                dataset_id=config.dataset_id,
                account_id=config.account_id,
            )
            if not events:
                return {"events": [], "clues": [], "stats": {}}

            query_vec = query_vector if query_vector is not None else await self.processor.generate_embedding(config.query)
            key_weight_map = {k.get("entity_id"): k.get("weight", 0.0) for k in key_final}

            # prepare adjacency via shared entities
            assoc_map = repo.get_entities_for_events(event_ids, tenant_id=config.tenant_id)

            base_scores: Dict[str, float] = {**event_scores}
            for ev in events:
                sim = cosine_similarity(query_vec, ev.content_vector or [])
                ents = assoc_map.get(str(ev.id), [])
                boost = sum(key_weight_map.get(str(e.id), 0.0) for e in ents)
                # merge recall score if present
                recall_score = event_scores.get(str(ev.id), 0.0)
                base_scores[str(ev.id)] = 0.5 * recall_score + 0.3 * sim + 0.2 * boost

            graph: Dict[str, Dict[str, float]] = {str(ev.id): {} for ev in events}

            # Build event-event edges by shared entities (faster than O(n^2) set intersections).
            entity_to_events: dict[str, list[str]] = {}
            for ev_id, ents in (assoc_map or {}).items():
                if ev_id not in graph:
                    continue
                for ent in (ents or []):
                    ent_id = str(getattr(ent, "id", "") or "")
                    if not ent_id:
                        continue
                    entity_to_events.setdefault(ent_id, []).append(ev_id)

            # Process entities by weight (key entities first) so edge budget keeps high-signal edges.
            entities_ordered = sorted(
                entity_to_events.items(),
                key=lambda kv: (-float(key_weight_map.get(kv[0], 0.1) or 0.1), kv[0]),
            )

            for ent_id, ev_list in entities_ordered:
                if not ev_list or len(ev_list) < 2:
                    continue

                w_ent = float(key_weight_map.get(ent_id, 0.1) or 0.1)
                ev_list = sorted(set(ev_list))
                for i, a in enumerate(ev_list):
                    for b in ev_list[i + 1 :]:
                        graph[a][b] = float(graph[a].get(b, 0.0) or 0.0) + w_ent
                        graph[b][a] = float(graph[b].get(a, 0.0) or 0.0) + w_ent

            scores = self._pagerank(
                graph,
                damping=config.rerank.pagerank_damping_factor,
                max_iter=config.rerank.pagerank_max_iterations,
                base_scores=base_scores,
            )

            results = format_events(events, scores, config.rerank.max_results)

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
        out_sum = {n: float(sum(graph.get(n, {}).values()) or 1.0) for n in nodes}
        teleport = {n: (1.0 - float(damping)) * float(base_scores.get(n, 0.0) or 0.0) for n in nodes}

        for _ in range(int(max_iter)):
            new_scores = dict(teleport)
            for src in nodes:
                edges = graph.get(src) or {}
                if not edges:
                    continue
                src_score = float(scores.get(src, 0.0) or 0.0)
                denom = float(out_sum.get(src, 1.0) or 1.0)
                if denom == 0.0:
                    continue
                scale = float(damping) * (src_score / denom)
                for dst, w in edges.items():
                    new_scores[dst] = float(new_scores.get(dst, 0.0) or 0.0) + scale * float(w or 0.0)
            scores = new_scores
        return scores
