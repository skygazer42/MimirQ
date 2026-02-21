"""
Expand stage: multi-hop entity -> event expansion.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Set

from app.core.config import settings
from app.rag.kg.repository import EntityRepository, EventRepository, RelationRepository, get_session
from app.rag.kg.search.config import SearchConfig
from app.rag.kg.search.recall import RecallResult
from app.rag.kg.search.relation_scoring import relation_multiplier
from app.rag.kg.search.tracker import Tracker


@dataclass
class ExpandResult:
    key_final: List[Dict[str, Any]]
    event_ids: List[str]
    clues: List[Dict[str, Any]]
    event_scores: Dict[str, float]


class ExpandSearcher:
    def __init__(self):
        ...

    async def expand(self, config: SearchConfig, recall_result: RecallResult) -> ExpandResult:
        if not config.expand.enabled:
            return ExpandResult(
                key_final=recall_result.key_final,
                event_ids=recall_result.event_ids,
                clues=recall_result.clues,
                event_scores=recall_result.event_scores,
            )

        tracker = Tracker()
        tracker.extend_clues(list(recall_result.clues or []))

        session = get_session()
        try:
            entity_repo = EntityRepository(session)
            event_repo = EventRepository(session)
            relation_repo = RelationRepository(session)
            tenant_id = config.tenant_id or settings.DEFAULT_TENANT_ID

            include_skills = bool(getattr(config, "include_skill_entities", True))
            skill_types = {"Skill", "SkillTag", "SkillCategory"}

            known_entities: Set[str] = {e["entity_id"] for e in recall_result.key_final if e.get("entity_id")}
            if not include_skills:
                known_entities = {
                    e["entity_id"]
                    for e in (recall_result.key_final or [])
                    if e.get("entity_id") and str(e.get("type") or "").strip() not in skill_types
                }
            entity_weights = dict(recall_result.key_weights)
            discovered_events: List[str] = list(recall_result.event_ids or [])
            discovered_event_ids: Set[str] = set(discovered_events)
            current_entities = [e["entity_id"] for e in (recall_result.key_final or []) if e.get("entity_id")]
            if not include_skills:
                current_entities = [
                    e["entity_id"]
                    for e in (recall_result.key_final or [])
                    if e.get("entity_id") and str(e.get("type") or "").strip() not in skill_types
                ]
            max_candidates = max(0, int(getattr(settings, "KG_SEARCH_MAX_RERANK_CANDIDATES", 0) or 0))

            for hop in range(config.expand.max_hops):
                if not current_entities:
                    break
                if max_candidates > 0 and len(discovered_event_ids) >= max_candidates:
                    break

                limit = int(config.expand.max_events_per_hop)
                if max_candidates > 0:
                    remaining = max(0, int(max_candidates) - int(len(discovered_event_ids)))
                    if remaining <= 0:
                        break
                    limit = max(1, min(limit, remaining))

                seed_entities = list(current_entities)
                if config.relation_expansion_enabled is None:
                    relation_enabled = bool(getattr(settings, "KG_SEARCH_RELATION_EXPANSION_ENABLED", False)) and bool(
                        getattr(settings, "KG_RELATION_ENABLED", False)
                    )
                else:
                    relation_enabled = bool(config.relation_expansion_enabled)

                if relation_enabled and seed_entities:
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
                            rel_rows = relation_repo.list_relations_for_entities(
                                seed_entities,
                                tenant_id=tenant_uuid,
                                document_ids=config.document_ids,
                                dataset_id=config.dataset_id,
                                account_id=config.account_id,
                                min_confidence=min_confidence if min_confidence > 0 else None,
                                limit=max_edges,
                            )

                            seed_set = set(seed_entities)
                            neighbor_weights: Dict[str, float] = {}
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
                                if subj in seed_set:
                                    from_id = subj
                                    to_id = obj
                                elif obj in seed_set:
                                    from_id = obj
                                    to_id = subj

                                if not from_id or not to_id or to_id == from_id:
                                    continue

                                pred_mult = relation_multiplier(predicate, from_is_subject=bool(from_id == subj))
                                if pred_mult <= 0:
                                    continue
                                w = (
                                    float(entity_weights.get(from_id, 0.0) or 0.0)
                                    * conf
                                    * float(weight_factor)
                                    * pred_mult
                                )
                                if w <= 0:
                                    continue

                                neighbor_weights[to_id] = max(neighbor_weights.get(to_id, 0.0), w)

                                tracker.add_clue(
                                    stage=f"expand-hop-{hop+1}",
                                    from_node=Tracker.build_entity_node(
                                        {"entity_id": from_id, "name": "", "type": "unknown", "hop": hop + 1}
                                    ),
                                    to_node=Tracker.build_entity_node(
                                        {"entity_id": to_id, "name": "", "type": "unknown", "hop": hop + 1}
                                    ),
                                    confidence=conf,
                                    relation=f"entity->entity:{predicate}" if predicate else "entity->entity",
                                    metadata={
                                        "method": "relation_expansion",
                                        "predicate": predicate,
                                        "predicate_multiplier": pred_mult,
                                        "step": f"hop-{hop+1}",
                                    },
                                )

                            sorted_neighbors = sorted(neighbor_weights.items(), key=lambda x: x[1], reverse=True)
                            sorted_neighbors = sorted_neighbors[:max_neighbors]
                            if sorted_neighbors and not include_skills:
                                # Filter out Skill-like neighbor nodes for "skills_off" ablations.
                                try:
                                    neighbor_ids = [eid for eid, _w in sorted_neighbors]
                                    objs = entity_repo.get_entities_by_ids(neighbor_ids, tenant_id=tenant_id)
                                    non_skill = {str(o.id) for o in (objs or []) if str(getattr(o, "type", "") or "") not in skill_types}
                                    sorted_neighbors = [(eid, w) for eid, w in sorted_neighbors if eid in non_skill]
                                except Exception:
                                    # Best-effort: if filtering fails, keep original neighbors.
                                    pass
                            for ent_id, w in sorted_neighbors:
                                if ent_id not in seed_set:
                                    seed_set.add(ent_id)
                                    seed_entities.append(ent_id)
                                entity_weights[ent_id] = max(entity_weights.get(ent_id, 0.0), w)

                events = event_repo.find_events_by_entities(
                    seed_entities,
                    tenant_id=tenant_id,
                    limit=limit,
                    document_ids=config.document_ids,
                    dataset_id=config.dataset_id,
                    account_id=config.account_id,
                )
                new_event_ids: List[str] = []
                for ev in events:
                    ev_id = str(ev.id)
                    if ev_id in discovered_event_ids:
                        continue
                    discovered_event_ids.add(ev_id)
                    new_event_ids.append(ev_id)
                if not new_event_ids:
                    break
                discovered_events.extend(new_event_ids)
                if max_candidates > 0 and len(discovered_event_ids) >= max_candidates:
                    break

                # score new events using existing entity weights
                assoc_map = event_repo.get_entities_for_events(new_event_ids, tenant_id=tenant_id)
                for ev in events:
                    ev_id = str(ev.id)
                    base = recall_result.event_scores.get(ev_id, 0.0)
                    boost = sum(
                        entity_weights.get(str(ent.id), 0.0) for ent in assoc_map.get(ev_id, [])
                    )
                    recall_result.event_scores[ev_id] = base * 0.5 + boost * 0.5

                # collect new entities from these events
                new_entities: Dict[str, float] = {}
                events_by_id = {str(ev.id): ev for ev in events}
                for ev_id, ents in assoc_map.items():
                    for ent in ents:
                        ent_id = str(ent.id)
                        if ent_id in known_entities:
                            continue
                        if not include_skills and str(getattr(ent, "type", "") or "") in skill_types:
                            continue
                        weight = recall_result.event_scores.get(ev_id, 0.0)
                        new_entities[ent_id] = new_entities.get(ent_id, 0.0) + weight
                        tracker.add_clue(
                            stage=f"expand-hop-{hop+1}",
                            from_node=Tracker.build_event_node(
                                events_by_id.get(ev_id) or {"id": ev_id},
                                stage=f"expand-hop-{hop+1}",
                                hop=hop + 1,
                            ),
                            to_node=Tracker.build_entity_node(
                                {"entity_id": ent_id, "name": ent.name, "type": ent.type, "hop": hop + 1}
                            ),
                            confidence=0.3,
                            relation="event->entity",
                            metadata={"step": f"hop-{hop+1}"},
                        )

                sorted_new = sorted(new_entities.items(), key=lambda x: x[1], reverse=True)
                sorted_new = sorted_new[: config.expand.entities_per_hop]
                if not sorted_new:
                    break

                current_entities = []
                for ent_id, w in sorted_new:
                    known_entities.add(ent_id)
                    entity_weights[ent_id] = entity_weights.get(ent_id, 0.0) * 0.5 + w * 0.5
                    current_entities.append(ent_id)

                min_events = int(getattr(config.expand, "min_events_per_hop", 0) or 0)
                if min_events > 0 and len(new_event_ids) < min_events:
                    break

            # build key_final list
            key_final: List[Dict[str, Any]] = []
            ent_objects = entity_repo.get_entities_by_ids(list(known_entities), tenant_id=tenant_id)
            for ent in ent_objects:
                if not include_skills and str(getattr(ent, "type", "") or "") in skill_types:
                    continue
                key_final.append(
                    {
                        "entity_id": str(ent.id),
                        "name": ent.name,
                        "type": ent.type,
                        "weight": entity_weights.get(str(ent.id), 0.0),
                    }
                )
            key_final.sort(key=lambda x: x["weight"], reverse=True)
            key_final = key_final[: config.recall.final_entity_count]

            return ExpandResult(
                key_final=key_final,
                event_ids=discovered_events,
                clues=tracker.get_clues(),
                event_scores=recall_result.event_scores,
            )
        finally:
            session.close()
