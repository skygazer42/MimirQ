"""
PageRank-style rerank combining query similarity and entity co-occurrence graph.
"""
import math
from typing import Any

from app.core.config import settings
from app.rag.kg.loading.processor import DocumentProcessor
from app.rag.kg.provenance import build_kg_path_provenance
from app.rag.kg.repository import EventRepository, get_session
from app.rag.kg.search.config import SearchConfig
from app.rag.kg.search.utils import cosine_similarity, format_events
from app.rag.retrieval.query_phrase_match import query_phrase_match


class RerankPageRankSearcher:
    def __init__(self):
        self.processor = DocumentProcessor()

    async def rerank(
        self,
        config: SearchConfig,
        event_ids: list[str],
        key_final: list[dict[str, Any]],
        event_scores: dict[str, float],
        *,
        query_vector: list[float] | None = None,
        event_hops: dict[str, int] | None = None,
    ) -> dict[str, Any]:
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
            key_entity_ids = {str(k.get("entity_id") or "").strip() for k in (key_final or []) if k.get("entity_id")}

            # prepare adjacency via shared entities
            assoc_map = repo.get_entities_for_events(event_ids, tenant_id=config.tenant_id)

            base_scores: dict[str, float] = {**event_scores}
            phrase_boost_weight = max(0.0, float(getattr(settings, "KG_SEARCH_EXACT_PHRASE_RERANK_BOOST", 0.25) or 0.0))
            for ev in events:
                sim = cosine_similarity(query_vec, ev.content_vector or [])
                ents = assoc_map.get(str(ev.id), [])
                boost = sum(key_weight_map.get(str(e.id), 0.0) for e in ents)
                phrase = query_phrase_match(
                    config.query,
                    f"{getattr(ev, 'title', '') or ''} {getattr(ev, 'summary', '') or ''} {getattr(ev, 'content', '') or ''}",
                )
                phrase_boost = float(phrase.get("score", 0.0) or 0.0) * phrase_boost_weight
                # merge recall score if present
                recall_score = event_scores.get(str(ev.id), 0.0)
                base_scores[str(ev.id)] = 0.5 * recall_score + 0.3 * sim + 0.2 * boost + phrase_boost

            graph: dict[str, dict[str, float]] = {str(ev.id): {} for ev in events}

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

            extras: dict[str, dict[str, Any]] = {}
            for ev in events:
                ev_id = str(getattr(ev, "id", "") or "")
                if not ev_id:
                    continue
                hop = 1
                if event_hops is not None:
                    try:
                        hop = int(event_hops.get(ev_id, 1) or 1)
                    except Exception:
                        hop = 1
                hop = max(1, min(hop, 5))

                shared = 0
                ents = assoc_map.get(ev_id, []) if isinstance(assoc_map, dict) else []
                for ent in ents or []:
                    ent_id = str(getattr(ent, "id", "") or "")
                    if ent_id and ent_id in key_entity_ids:
                        shared += 1
                shared = max(0, min(shared, 5))

                extras[ev_id] = {
                    "kg_path_length": int(hop),
                    "kg_shared_events": int(shared),
                    "kg_evidence_anchored": bool(getattr(ev, "chunk_id", None)),
                }
                phrase = query_phrase_match(
                    config.query,
                    f"{getattr(ev, 'title', '') or ''} {getattr(ev, 'summary', '') or ''} {getattr(ev, 'content', '') or ''}",
                )
                if float(phrase.get("score", 0.0) or 0.0) > 0.0:
                    extras[ev_id]["kg_exact_phrase_score"] = float(phrase.get("score", 0.0) or 0.0)
                    extras[ev_id]["kg_exact_phrase_matches"] = list(phrase.get("matched_phrases") or [])[:4]
                path = build_kg_path_provenance(entities=ents, key_entity_ids=key_entity_ids, max_entities=4)
                if path:
                    extras[ev_id]["kg_path"] = path

            results = format_events(events, scores, config.rerank.max_results, extra_by_event_id=extras)

            return {
                "events": results,
                "clues": [],
                "stats": {"total_candidates": len(events), "returned": len(results)},
            }
        finally:
            session.close()

    def _pagerank(
        self,
        graph: dict[str, dict[str, float]],
        damping: float,
        max_iter: int,
        base_scores: dict[str, float],
    ) -> dict[str, float]:
        nodes = list(graph.keys())
        if not nodes:
            return {}
        scores = dict.fromkeys(nodes, 1.0)
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
                if math.isclose(denom, 0.0, abs_tol=1e-12):
                    continue
                scale = float(damping) * (src_score / denom)
                for dst, w in edges.items():
                    new_scores[dst] = float(new_scores.get(dst, 0.0) or 0.0) + scale * float(w or 0.0)
            scores = new_scores
        return scores
