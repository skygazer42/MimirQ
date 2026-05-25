"""
Reciprocal Rank Fusion reranker combining recall score and query similarity.
"""
from typing import Any

from app.core.config import settings
from app.rag.kg.loading.processor import DocumentProcessor
from app.rag.kg.provenance import build_kg_path_provenance
from app.rag.kg.repository import EventRepository, get_session
from app.rag.kg.search.config import SearchConfig
from app.rag.kg.search.utils import cosine_similarity, format_events
from app.rag.retrieval.query_phrase_match import query_phrase_match


class RerankRRFSearcher:
    def __init__(self, *args, **kwargs):
        self.processor = DocumentProcessor()

    def _load_document_labels(self, session: Any, events: list[Any]) -> dict[str, str]:
        doc_ids = {
            str(getattr(ev, "document_id", "") or "").strip()
            for ev in (events or [])
            if str(getattr(ev, "document_id", "") or "").strip()
        }
        if not doc_ids:
            return {}
        try:
            from app.models.document import Document as DBDocument  # noqa: WPS433

            rows = (
                session.query(DBDocument.id, DBDocument.filename, DBDocument.doc_metadata)
                .filter(DBDocument.id.in_(list(doc_ids)))
                .all()
            )
        except Exception:
            return {}

        labels: dict[str, str] = {}
        for doc_id, filename, metadata in rows:
            parts = [str(filename or "")]
            if isinstance(metadata, dict):
                for key in ("title", "name", "original_filename"):
                    value = metadata.get(key)
                    if value:
                        parts.append(str(value))
                user = metadata.get("user")
                if isinstance(user, dict):
                    for key in ("title", "name"):
                        value = user.get(key)
                        if value:
                            parts.append(str(value))
            labels[str(doc_id)] = " ".join(p for p in parts if p.strip())
        return labels

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
            input_order = {str(eid): idx for idx, eid in enumerate(event_ids)}

            # Rank1: recall scores
            recall_scores = {str(eid): float(event_scores.get(str(eid), 0.0) or 0.0) for eid in event_ids if eid}
            recall_rank = sorted(
                recall_scores.items(),
                key=lambda x: (-x[1], int(input_order.get(str(x[0]), len(event_ids))), str(x[0])),
            )
            recall_order = {eid: idx for idx, (eid, _) in enumerate(recall_rank)}

            # Rank2: query similarity
            sim_scores = {}
            for ev in events:
                sim = cosine_similarity(query_vec, ev.content_vector or [])
                sim_scores[str(ev.id)] = sim
            sim_rank = sorted(
                sim_scores.items(),
                key=lambda x: (-x[1], int(input_order.get(str(x[0]), len(event_ids))), str(x[0])),
            )
            sim_order = {eid: idx for idx, (eid, _) in enumerate(sim_rank)}

            fused = {}
            k = config.rerank.rrf_k
            phrase_boost_weight = max(0.0, float(getattr(settings, "KG_SEARCH_EXACT_PHRASE_RERANK_BOOST", 0.25) or 0.0))
            events_by_id = {str(getattr(ev, "id", "") or ""): ev for ev in events}
            document_labels = self._load_document_labels(session, events)
            for eid in event_ids:
                r1 = recall_order.get(str(eid), len(event_ids))
                r2 = sim_order.get(str(eid), len(event_ids))
                ev = events_by_id.get(str(eid))
                phrase_boost = 0.0
                if ev is not None and phrase_boost_weight > 0.0:
                    event_phrase = query_phrase_match(
                        config.query,
                        f"{getattr(ev, 'title', '') or ''} {getattr(ev, 'summary', '') or ''} {getattr(ev, 'content', '') or ''}",
                    )
                    doc_label = document_labels.get(str(getattr(ev, "document_id", "") or "").strip(), "")
                    doc_phrase = query_phrase_match(config.query, doc_label) if doc_label else {"score": 0.0}
                    phrase_boost = (
                        float(event_phrase.get("score", 0.0) or 0.0) * phrase_boost_weight
                        + float(doc_phrase.get("score", 0.0) or 0.0) * phrase_boost_weight * 0.8
                    )
                fused[str(eid)] = 1.0 / (k + r1) + 1.0 / (k + r2) + phrase_boost

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
                phrase = query_phrase_match(
                    config.query,
                    f"{getattr(ev, 'title', '') or ''} {getattr(ev, 'summary', '') or ''} {getattr(ev, 'content', '') or ''}",
                )
                if float(phrase.get("score", 0.0) or 0.0) > 0.0:
                    extras[ev_id]["kg_exact_phrase_score"] = float(phrase.get("score", 0.0) or 0.0)
                    extras[ev_id]["kg_exact_phrase_matches"] = list(phrase.get("matched_phrases") or [])[:4]
                doc_label = document_labels.get(str(getattr(ev, "document_id", "") or "").strip(), "")
                doc_phrase = query_phrase_match(config.query, doc_label) if doc_label else {"score": 0.0}
                if float(doc_phrase.get("score", 0.0) or 0.0) > 0.0:
                    extras[ev_id]["kg_source_document_phrase_score"] = float(doc_phrase.get("score", 0.0) or 0.0)
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
