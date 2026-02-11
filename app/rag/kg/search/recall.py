"""
Recall stage: 8-step pipeline (query -> keys -> events -> weights).
"""
from dataclasses import dataclass
from typing import Any, Dict, List

from app.core.config import settings
from app.rag.kg.loading.processor import DocumentProcessor
from app.rag.kg.repository import EntityRepository, EventRepository, get_session
from app.rag.kg.search.config import SearchConfig
from app.rag.kg.search.tracker import Tracker
from app.rag.kg.search.utils import cosine_similarity


@dataclass
class RecallResult:
    query_vector: List[float]
    key_final: List[Dict[str, Any]]
    event_ids: List[str]
    clues: List[Dict[str, Any]]
    key_weights: Dict[str, float]
    event_scores: Dict[str, float]


class RecallSearcher:
    def __init__(self):
        self.processor = DocumentProcessor()

    async def search(self, config: SearchConfig) -> RecallResult:
        tracker = Tracker()
        session = get_session()
        try:
            entity_repo = EntityRepository(session)
            event_repo = EventRepository(session)
            tenant_id = config.tenant_id or settings.DEFAULT_TENANT_ID
            max_events = int(config.recall.max_events)
            max_candidates = max(0, int(getattr(settings, "KG_SEARCH_MAX_RERANK_CANDIDATES", 0) or 0))
            if max_candidates > 0:
                max_events = min(max_events, max_candidates)

            # === Step1: query -> keys (vector) ===
            query_vec = await self.processor.generate_embedding(config.query)
            raw_entities = entity_repo.search_similar(
                query_vector=query_vec,
                tenant_id=tenant_id,
                k=config.recall.vector_candidates,
            )
            if raw_entities and (config.document_ids or config.dataset_id):
                # Prevent cross-document leakage within tenant: only keep entities that appear
                # in events scoped by the requested documents or dataset.
                from uuid import UUID

                candidate_ids = [e.get("entity_id") or e.get("id") for e in raw_entities]
                allowed_entity_ids: set[UUID] | None = None
                if config.document_ids:
                    allowed_entity_ids = event_repo.filter_entity_ids_in_documents(
                        candidate_ids,
                        tenant_id=tenant_id,
                        document_ids=config.document_ids,
                    )
                elif config.dataset_id:
                    if not config.account_id:
                        raise ValueError("account_id is required for dataset-scoped KG search")
                    allowed_entity_ids = event_repo.filter_entity_ids_in_dataset(
                        candidate_ids,
                        tenant_id=tenant_id,
                        dataset_id=config.dataset_id,
                        account_id=config.account_id,
                    )

                if allowed_entity_ids is not None:
                    filtered_entities: List[dict] = []
                    for ent in raw_entities:
                        ent_id = ent.get("entity_id") or ent.get("id")
                        if ent_id is None:
                            continue
                        try:
                            ent_uuid = UUID(str(ent_id))
                        except Exception:
                            continue
                        if ent_uuid in allowed_entity_ids:
                            filtered_entities.append(ent)
                    raw_entities = filtered_entities
            key_query_related = [
                e for e in raw_entities if e.get("similarity", 0.0) >= config.recall.entity_similarity_threshold
            ][: config.recall.max_entities]

            # clues
            for ent in key_query_related:
                tracker.add_clue(
                    stage="recall",
                    from_node=Tracker.build_query_node(config),
                    to_node=Tracker.build_entity_node(ent),
                    confidence=ent.get("similarity", 0.0),
                    relation="query->entity",
                    metadata={"method": "vector_search", "step": "step1"},
                )

            # normalize key weights
            key_weights: Dict[str, float] = {}
            if key_query_related:
                sims = [e.get("similarity", 0.0) for e in key_query_related]
                mx = max(sims) or 1.0
                for ent in key_query_related:
                    key_weights[ent["entity_id"]] = ent.get("similarity", 0.0) / mx

            # === Step2: keys -> events (entity relation) ===
            event_ids_from_entities = event_repo.search_events_by_entities(
                [e["entity_id"] for e in key_query_related],
                tenant_id=tenant_id,
                limit=config.recall.vector_candidates * 2,
                document_ids=config.document_ids,
                dataset_id=config.dataset_id,
                account_id=config.account_id,
            )
            event_ids_from_entities = list(event_ids_from_entities)[: config.rerank.max_key_recall_results]

            # === Step3: query -> events (vector) ===
            content_results = event_repo.search_similar_by_content(
                query_vector=query_vec,
                tenant_id=tenant_id,
                k=config.recall.vector_candidates,
                document_ids=config.document_ids,
                dataset_id=config.dataset_id,
                account_id=config.account_id,
            )
            event_query_related = [
                item
                for item in content_results
                if item.get("similarity", 0.0) >= config.recall.event_similarity_threshold
            ]
            event_query_related = event_query_related[: config.rerank.max_query_recall_results]

            for ev in event_query_related:
                tracker.add_clue(
                    stage="recall",
                    from_node=Tracker.build_query_node(config),
                    to_node=Tracker.build_event_node({"id": ev["event_id"], "title": ev.get("title")}),
                    confidence=ev.get("similarity", 0.0),
                    relation="query->event",
                    metadata={"method": "vector_search", "step": "step3"},
                )

            # === Step4: merge events ===
            merged_event_ids = list(
                dict.fromkeys(event_ids_from_entities + [e["event_id"] for e in event_query_related])
            )[:max_events]

            # === Step5/6: compute event-key weights & event scores ===
            events_detail = event_repo.get_events_by_ids(
                merged_event_ids,
                tenant_id=tenant_id,
                document_ids=config.document_ids,
                dataset_id=config.dataset_id,
                account_id=config.account_id,
            )
            merged_event_ids = [str(ev.id) for ev in events_detail]
            assoc_map = event_repo.get_event_entities(merged_event_ids, tenant_id=tenant_id)

            event_scores: Dict[str, float] = {}
            for ev in events_detail:
                ev_id = str(ev.id)
                sim = 0.0
                if ev.content_vector:
                    sim = cosine_similarity(query_vec, ev.content_vector)
                # entity weight sum for recalled keys
                boost = 0.0
                for link in assoc_map.get(ev_id, []):
                    boost += key_weights.get(str(link.entity_id), 0.0)
                # combine
                event_scores[ev_id] = sim * 0.6 + boost * 0.4

            # sort events by score and trim
            merged_event_ids.sort(key=lambda eid: event_scores.get(str(eid), 0.0), reverse=True)
            merged_event_ids = merged_event_ids[:max_events]

            # === Step7: backprop key weights from events ===
            key_event_weights: Dict[str, float] = {}
            for ev_id in merged_event_ids:
                ev_weight = event_scores.get(str(ev_id), 0.0)
                for link in assoc_map.get(str(ev_id), []):
                    key_event_weights[str(link.entity_id)] = key_event_weights.get(str(link.entity_id), 0.0) + ev_weight

            # merge key weights (query & event)
            for k, v in key_event_weights.items():
                key_weights[k] = key_weights.get(k, 0.0) * 0.5 + v * 0.5

            # === Step8: select final keys ===
            key_final = [
                {
                    **e,
                    "weight": key_weights.get(e["entity_id"], 0.0),
                }
                for e in key_query_related
                if key_weights.get(e["entity_id"], 0.0) >= config.recall.entity_weight_threshold
            ]
            key_final.sort(key=lambda x: x.get("weight", 0.0), reverse=True)
            key_final = key_final[: config.recall.final_entity_count]

            return RecallResult(
                query_vector=query_vec,
                key_final=key_final,
                event_ids=merged_event_ids,
                clues=tracker.get_clues(),
                key_weights=key_weights,
                event_scores=event_scores,
            )
        finally:
            session.close()
