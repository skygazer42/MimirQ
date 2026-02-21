"""
Recall stage: 8-step pipeline (query -> keys -> events -> weights).
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.core.config import settings
from app.rag.kg.loading.processor import DocumentProcessor
from app.rag.kg.repository import EntityRepository, EventRepository, RelationRepository, get_session
from app.rag.kg.search.config import SearchConfig
from app.rag.kg.search.relation_scoring import relation_multiplier
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
    relation_debug: Dict[str, Any] = field(default_factory=dict)


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
            if not bool(getattr(config, "include_skill_entities", True)):
                raw_entities = [
                    e
                    for e in (raw_entities or [])
                    if str((e or {}).get("type") or "").strip() not in {"Skill", "SkillTag", "SkillCategory"}
                ]
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

            # === Optional Step1.5: keys -> neighbor entities (relations) ===
            relation_neighbor_ids: List[str] = []
            relation_debug: Dict[str, Any] = {"enabled": False}
            if config.relation_expansion_enabled is None:
                relation_enabled = bool(getattr(settings, "KG_SEARCH_RELATION_EXPANSION_ENABLED", False)) and bool(
                    getattr(settings, "KG_RELATION_ENABLED", False)
                )
            else:
                # Per-call override (used by diagnostics/ablations). This intentionally bypasses
                # the global KG_RELATION_ENABLED guard so experiments can be run safely without
                # mutating process-wide settings.
                relation_enabled = bool(config.relation_expansion_enabled)

            if relation_enabled and key_query_related:
                max_neighbors = max(0, int(getattr(settings, "KG_SEARCH_RELATION_MAX_NEIGHBORS", 0) or 0))
                if max_neighbors > 0:
                    min_confidence = float(getattr(settings, "KG_SEARCH_RELATION_MIN_CONFIDENCE", 0.0) or 0.0)
                    max_edges = max(0, int(getattr(settings, "KG_SEARCH_RELATION_MAX_EDGES", 0) or 0))
                    if max_edges <= 0:
                        max_edges = 500
                    weight_factor = float(
                        getattr(settings, "KG_SEARCH_RELATION_NEIGHBOR_WEIGHT_FACTOR", 0.7) or 0.7
                    )

                    try:
                        from uuid import UUID

                        tenant_uuid = UUID(str(tenant_id))
                    except Exception:
                        tenant_uuid = None

                    if tenant_uuid is not None:
                        relation_debug = {
                            "enabled": True,
                            "min_confidence": float(min_confidence),
                            "max_edges": int(max_edges),
                            "max_neighbors": int(max_neighbors),
                            "weight_factor": float(weight_factor),
                        }
                        rel_repo = RelationRepository(session)
                        rel_rows = rel_repo.list_relations_for_entities(
                            [e["entity_id"] for e in key_query_related],
                            tenant_id=tenant_uuid,
                            document_ids=config.document_ids,
                            dataset_id=config.dataset_id,
                            account_id=config.account_id,
                            min_confidence=min_confidence if min_confidence > 0 else None,
                            limit=max_edges,
                        )
                        relation_debug["edges_fetched"] = int(len(rel_rows))

                        key_entity_map = {e.get("entity_id"): e for e in key_query_related if e.get("entity_id")}
                        neighbor_weights: Dict[str, float] = {}
                        predicate_hist: Dict[str, int] = {}
                        edges_used = 0
                        for rel in rel_rows:
                            subj = str(getattr(rel, "subject_entity_id", "") or "")
                            obj = str(getattr(rel, "object_entity_id", "") or "")
                            if not subj or not obj:
                                continue

                            predicate = str(getattr(rel, "predicate", "") or "").strip()
                            if not predicate or predicate.casefold() == "unknown":
                                continue
                            conf = float(getattr(rel, "confidence", 0.0) or 0.0)
                            if conf <= 0:
                                continue

                            from_id: str | None = None
                            to_id: str | None = None
                            if subj in key_weights:
                                from_id = subj
                                to_id = obj
                            elif obj in key_weights:
                                from_id = obj
                                to_id = subj

                            if not from_id or not to_id or to_id == from_id:
                                continue

                            pred_mult = relation_multiplier(predicate, from_is_subject=bool(from_id == subj))
                            if pred_mult <= 0:
                                continue
                            w = float(key_weights.get(from_id, 0.0) or 0.0) * conf * float(weight_factor) * pred_mult
                            if w <= 0:
                                continue

                            neighbor_weights[to_id] = max(neighbor_weights.get(to_id, 0.0), w)
                            predicate_hist[predicate] = int(predicate_hist.get(predicate, 0) or 0) + 1
                            edges_used += 1

                            tracker.add_clue(
                                stage="recall",
                                from_node=Tracker.build_entity_node(
                                    key_entity_map.get(from_id) or {"entity_id": from_id, "name": "", "type": "unknown"}
                                ),
                                to_node=Tracker.build_entity_node({"entity_id": to_id, "name": "", "type": "unknown"}),
                                confidence=conf,
                                relation=f"entity->entity:{predicate}" if predicate else "entity->entity",
                                metadata={
                                    "method": "relation_expansion",
                                    "predicate": predicate,
                                    "predicate_multiplier": pred_mult,
                                    "step": "step1.5",
                                },
                            )

                        sorted_neighbors = sorted(neighbor_weights.items(), key=lambda x: x[1], reverse=True)
                        sorted_neighbors = sorted_neighbors[:max_neighbors]
                        relation_neighbor_ids = [eid for eid, _w in sorted_neighbors]
                        for ent_id, w in sorted_neighbors:
                            key_weights[ent_id] = max(key_weights.get(ent_id, 0.0), w)
                        relation_debug["edges_used"] = int(edges_used)
                        relation_debug["neighbors_total"] = int(len(neighbor_weights))
                        relation_debug["neighbors_selected"] = int(len(sorted_neighbors))
                        relation_debug["predicate_hist"] = dict(sorted(predicate_hist.items(), key=lambda x: (-x[1], x[0])))  # type: ignore[assignment]

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

            event_ids_from_relation_entities: List[str] = []
            if relation_neighbor_ids:
                rel_event_ids = event_repo.search_events_by_entities(
                    relation_neighbor_ids,
                    tenant_id=tenant_id,
                    limit=config.recall.vector_candidates * 2,
                    document_ids=config.document_ids,
                    dataset_id=config.dataset_id,
                    account_id=config.account_id,
                )
                event_ids_from_relation_entities = list(rel_event_ids)[: config.rerank.max_key_recall_results]

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
                dict.fromkeys(
                    list(event_ids_from_entities)
                    + list(event_ids_from_relation_entities)
                    + [e["event_id"] for e in event_query_related]
                )
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
                relation_debug=relation_debug,
            )
        finally:
            session.close()
