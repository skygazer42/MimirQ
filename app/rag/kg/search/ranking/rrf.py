"""
Reciprocal Rank Fusion reranker combining recall score and query similarity.
"""
from typing import Any

from app.rag.kg.loading.processor import DocumentProcessor
from app.rag.kg.provenance import build_kg_path_provenance
from app.rag.kg.repository import EventRepository, get_session
from app.rag.kg.search.config import SearchConfig
from app.rag.kg.search.utils import cosine_similarity, format_events


class RerankRRFSearcher:
    def __init__(self, *args, **kwargs):
        self.processor = DocumentProcessor()

    async def rerank(
        self,
        config: SearchConfig,
        event_ids: list[str],
        event_scores: dict[str, float],
        *,
        query_vector: list[float] | None = None,
        key_final: list[dict[str, Any]] | None = None,
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

            # Rank1: recall scores
            recall_scores = {str(eid): float(event_scores.get(str(eid), 0.0) or 0.0) for eid in event_ids if eid}
            recall_rank = sorted(recall_scores.items(), key=lambda x: (-x[1], x[0]))
            recall_order = {eid: idx for idx, (eid, _) in enumerate(recall_rank)}

            # Rank2: query similarity
            sim_scores = {}
            for ev in events:
                sim = cosine_similarity(query_vec, ev.content_vector or [])
                sim_scores[str(ev.id)] = sim
            sim_rank = sorted(sim_scores.items(), key=lambda x: (-x[1], x[0]))
            sim_order = {eid: idx for idx, (eid, _) in enumerate(sim_rank)}

            fused = {}
            k = config.rerank.rrf_k
            for eid in event_ids:
                r1 = recall_order.get(str(eid), len(event_ids))
                r2 = sim_order.get(str(eid), len(event_ids))
                fused[str(eid)] = 1.0 / (k + r1) + 1.0 / (k + r2)

            extras: dict[str, dict[str, Any]] = {}
            key_entity_ids = {str(k.get("entity_id") or "").strip() for k in (key_final or []) if k.get("entity_id")}
            assoc_map: dict[str, list[Any]] = {}
            if key_entity_ids:
                try:
                    assoc_map = repo.get_entities_for_events(event_ids, tenant_id=config.tenant_id)
                except Exception:
                    assoc_map = {}
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
                path = build_kg_path_provenance(entities=ents, key_entity_ids=key_entity_ids, max_entities=4)
                if path:
                    extras[ev_id]["kg_path"] = path

            results = format_events(events, fused, config.rerank.max_results, extra_by_event_id=extras)

            return {
                "events": results,
                "clues": [],
                "stats": {"total_candidates": len(events), "returned": len(results)},
            }
        finally:
            session.close()
