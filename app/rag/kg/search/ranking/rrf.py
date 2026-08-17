"""
Reciprocal Rank Fusion reranker combining recall score and query similarity.
"""

from typing import Any

from app.core.config import settings
from app.rag.kg.loading.processor import DocumentProcessor
from app.rag.kg.repository import EventRepository, get_session
from app.rag.kg.search.config import SearchConfig
from app.rag.kg.search.ranking.features import (
    base_event_extras,
    clamped_hop,
    document_phrase_metadata,
    event_document_id,
    event_id,
    event_search_text,
    exact_phrase_metadata,
    kg_path_metadata,
    phrase_score,
    shared_key_entity_count,
)
from app.rag.kg.search.utils import cosine_similarity, format_events


def _event_document_ids(events: list[Any]) -> set[str]:
    return {event_document_id(event) for event in events or [] if event_document_id(event)}


def _metadata_label_parts(metadata: Any) -> list[str]:
    if not isinstance(metadata, dict):
        return []
    parts = [str(metadata[key]) for key in ("title", "name", "original_filename") if metadata.get(key)]
    user = metadata.get("user")
    if isinstance(user, dict):
        parts.extend(str(user[key]) for key in ("title", "name") if user.get(key))
    return parts


def _document_label(filename: Any, metadata: Any) -> str:
    parts = [str(filename or ""), *_metadata_label_parts(metadata)]
    return " ".join(part for part in parts if part.strip())


def _rank_order(scores: dict[str, float], input_order: dict[str, int], fallback_rank: int) -> dict[str, int]:
    ranked = sorted(
        scores.items(),
        key=lambda item: (-item[1], int(input_order.get(str(item[0]), fallback_rank)), str(item[0])),
    )
    return {item_id: idx for idx, (item_id, _) in enumerate(ranked)}


def _similarity_scores(events: list[Any], query_vec: list[float]) -> dict[str, float]:
    return {
        event_id(event): cosine_similarity(query_vec, getattr(event, "content_vector", None) or []) for event in events
    }


def _rrf_phrase_boost(
    *,
    query: str,
    event: Any | None,
    document_labels: dict[str, str],
    phrase_boost_weight: float,
) -> float:
    if event is None or phrase_boost_weight <= 0.0:
        return 0.0
    event_boost = phrase_score(query, event_search_text(event)) * phrase_boost_weight
    doc_label = document_labels.get(event_document_id(event), "")
    doc_boost = phrase_score(query, doc_label) * phrase_boost_weight * 0.8 if doc_label else 0.0
    return float(event_boost + doc_boost)


def _fused_scores(
    *,
    event_ids: list[str],
    recall_order: dict[str, int],
    sim_order: dict[str, int],
    events_by_id: dict[str, Any],
    document_labels: dict[str, str],
    query: str,
    rrf_k: int,
    phrase_boost_weight: float,
) -> dict[str, float]:
    fused: dict[str, float] = {}
    fallback_rank = len(event_ids)
    for raw_id in event_ids:
        item_id = str(raw_id)
        phrase_boost = _rrf_phrase_boost(
            query=query,
            event=events_by_id.get(item_id),
            document_labels=document_labels,
            phrase_boost_weight=phrase_boost_weight,
        )
        fused[item_id] = 1.0 / (rrf_k + recall_order.get(item_id, fallback_rank))
        fused[item_id] += 1.0 / (rrf_k + sim_order.get(item_id, fallback_rank)) + phrase_boost
    return fused


def _safe_assoc_map(
    repo: EventRepository, event_ids: list[str], tenant_id: Any, key_entity_ids: set[str]
) -> dict[str, list[Any]]:
    if not key_entity_ids:
        return {}
    try:
        return repo.get_entities_for_events(event_ids, tenant_id=tenant_id)
    except Exception:
        return {}


def _build_extras(
    *,
    events: list[Any],
    assoc_map: dict[str, list[Any]],
    key_entity_ids: set[str],
    event_hops: dict[str, int] | None,
    document_labels: dict[str, str],
    query: str,
) -> dict[str, dict[str, Any]]:
    extras: dict[str, dict[str, Any]] = {}
    for event in events:
        item_id = event_id(event)
        if not item_id:
            continue
        entities = assoc_map.get(item_id, []) if isinstance(assoc_map, dict) else []
        extra = base_event_extras(
            event,
            hop=clamped_hop(event_hops, item_id),
            shared=shared_key_entity_count(entities, key_entity_ids),
        )
        extra.update(exact_phrase_metadata(query, event))
        extra.update(document_phrase_metadata(query, document_labels.get(event_document_id(event), "")))
        extra.update(kg_path_metadata(entities, key_entity_ids))
        extras[item_id] = extra
    return extras


class RerankRRFSearcher:
    def __init__(self, *args, **kwargs):
        self.processor = DocumentProcessor()

    def _load_document_labels(self, session: Any, events: list[Any]) -> dict[str, str]:
        doc_ids = _event_document_ids(events)
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

        return {str(doc_id): _document_label(filename, metadata) for doc_id, filename, metadata in rows}

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

            query_vec = (
                query_vector if query_vector is not None else await self.processor.generate_embedding(config.query)
            )
            input_order = {str(item_id): idx for idx, item_id in enumerate(event_ids)}
            recall_scores = {
                str(item_id): float(event_scores.get(str(item_id), 0.0) or 0.0) for item_id in event_ids if item_id
            }
            recall_order = _rank_order(recall_scores, input_order, len(event_ids))
            sim_order = _rank_order(_similarity_scores(events, query_vec), input_order, len(event_ids))
            phrase_boost_weight = max(0.0, float(getattr(settings, "KG_SEARCH_EXACT_PHRASE_RERANK_BOOST", 0.25) or 0.0))
            events_by_id = {event_id(event): event for event in events}
            document_labels = self._load_document_labels(session, events)
            fused = _fused_scores(
                event_ids=event_ids,
                recall_order=recall_order,
                sim_order=sim_order,
                events_by_id=events_by_id,
                document_labels=document_labels,
                query=config.query,
                rrf_k=config.rerank.rrf_k,
                phrase_boost_weight=phrase_boost_weight,
            )
            key_entity_ids = {str(k.get("entity_id") or "").strip() for k in (key_final or []) if k.get("entity_id")}
            assoc_map = _safe_assoc_map(repo, event_ids, config.tenant_id, key_entity_ids)
            extras = _build_extras(
                events=events,
                assoc_map=assoc_map,
                key_entity_ids=key_entity_ids,
                event_hops=event_hops,
                document_labels=document_labels,
                query=config.query,
            )

            results = format_events(events, fused, config.rerank.max_results, extra_by_event_id=extras)

            return {
                "events": results,
                "clues": [],
                "stats": {"total_candidates": len(events), "returned": len(results)},
            }
        finally:
            session.close()
