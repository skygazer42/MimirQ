"""
Expand stage: multi-hop entity -> event expansion.
"""

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.rag.kg.repository import EntityRepository, EventRepository, RelationRepository, get_session
from app.rag.kg.search.config import SearchConfig
from app.rag.kg.search.recall import RecallResult
from app.rag.kg.search.relation_scoring import relation_direction, relation_evidence, relation_multiplier
from app.rag.kg.search.tracker import Tracker, build_entity_node, build_event_node
from app.rag.kg.search.utils import confidence_bucket

if TYPE_CHECKING:
    from app.rag.kg.models import KgEntity, KgRelation, KgSourceEvent

logger = get_logger(__name__)

_SKILL_TYPES = {"Skill", "SkillTag", "SkillCategory"}


@dataclass
class ExpandResult:
    key_final: list[dict[str, Any]]
    event_ids: list[str]
    clues: list[dict[str, Any]]
    event_scores: dict[str, float]
    event_hops: dict[str, int]


@dataclass
class _ExpandState:
    known_entities: set[str]
    entity_weights: dict[str, float]
    discovered_events: list[str]
    discovered_event_ids: set[str]
    event_hops: dict[str, int]
    current_entities: list[str]


def _empty_scope_result(recall_result: RecallResult) -> ExpandResult:
    return ExpandResult(
        key_final=[],
        event_ids=[],
        clues=list(recall_result.clues or []),
        event_scores={},
        event_hops={},
    )


def _disabled_expand_result(recall_result: RecallResult) -> ExpandResult:
    return ExpandResult(
        key_final=recall_result.key_final,
        event_ids=recall_result.event_ids,
        clues=recall_result.clues,
        event_scores=recall_result.event_scores,
        event_hops=dict(recall_result.event_hops or {}),
    )


def _is_skill_type(value: object) -> bool:
    return str(value or "").strip() in _SKILL_TYPES


def _entity_ids(items: list[dict[str, Any]], *, include_skills: bool) -> list[str]:
    return [
        item["entity_id"]
        for item in (items or [])
        if item.get("entity_id") and (include_skills or not _is_skill_type(item.get("type")))
    ]


def _build_expand_state(recall_result: RecallResult, *, include_skills: bool) -> _ExpandState:
    discovered_events = [str(event_id) for event_id in (recall_result.event_ids or []) if str(event_id)]
    event_hops = dict(recall_result.event_hops or {})
    for event_id in discovered_events:
        if event_id not in event_hops:
            event_hops[event_id] = 2
    return _ExpandState(
        known_entities=set(_entity_ids(list(recall_result.key_final or []), include_skills=include_skills)),
        entity_weights=dict(recall_result.key_weights),
        discovered_events=discovered_events,
        discovered_event_ids=set(discovered_events),
        event_hops=event_hops,
        current_entities=_entity_ids(list(recall_result.key_final or []), include_skills=include_skills),
    )


def _resolve_expand_limit(
    config: SearchConfig,
    *,
    discovered_count: int,
    max_candidates: int,
) -> int:
    limit = int(config.expand.max_events_per_hop)
    if max_candidates <= 0:
        return limit
    remaining = max(0, int(max_candidates) - int(discovered_count))
    if remaining <= 0:
        return 0
    return max(1, min(limit, remaining))


def _relation_expansion_enabled(config: SearchConfig) -> bool:
    if config.relation_expansion_enabled is not None:
        return bool(config.relation_expansion_enabled)
    return bool(settings.KG_SEARCH_RELATION_EXPANSION_ENABLED) and bool(settings.KG_RELATION_ENABLED)


def _tenant_uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except Exception:
        return None


def _relation_neighbor_candidate(
    rel: "KgRelation",
    *,
    seed_set: set[str],
    entity_weights: dict[str, float],
    weight_factor: float,
) -> tuple[str, str, str, float, float, float, str, float] | None:
    from_id, to_id, predicate = relation_direction(rel, seed_set)
    if not from_id or not to_id or not predicate or to_id == from_id:
        return None
    confidence = float(rel.confidence or 0.0)
    if confidence <= 0:
        return None
    pred_mult = relation_multiplier(
        predicate,
        from_is_subject=bool(from_id == str(rel.subject_entity_id)),
    )
    if pred_mult <= 0:
        return None
    evidence_mult, evidence_source = relation_evidence(rel, settings=settings)
    weight = (
        float(entity_weights.get(from_id, 0.0) or 0.0) * confidence * float(weight_factor) * pred_mult * evidence_mult
    )
    if weight <= 0:
        return None
    return from_id, to_id, predicate, confidence, pred_mult, evidence_mult, evidence_source, weight


def _add_relation_clue(
    tracker: Tracker,
    *,
    rel: "KgRelation",
    hop: int,
    from_id: str,
    to_id: str,
    predicate: str,
    confidence: float,
    pred_mult: float,
    evidence_mult: float,
    evidence_source: str,
    bucket_low: float,
    bucket_mid: float,
) -> None:
    bucket = confidence_bucket(confidence, low_max=bucket_low, mid_max=bucket_mid)
    tracker.add_clue(
        stage=f"expand-hop-{hop + 1}",
        from_node=build_entity_node({"entity_id": from_id, "name": "", "type": "unknown", "hop": hop + 1}),
        to_node=build_entity_node({"entity_id": to_id, "name": "", "type": "unknown", "hop": hop + 1}),
        confidence=confidence,
        relation=f"entity->entity:{predicate}" if predicate else "entity->entity",
        metadata={
            "method": "relation_expansion",
            "predicate": predicate,
            "predicate_multiplier": pred_mult,
            "evidence_multiplier": float(evidence_mult),
            "evidence_source": evidence_source,
            "confidence_bucket": bucket,
            "relation_id": str(rel.id),
            "relation_document_id": str(rel.document_id) if rel.document_id is not None else None,
            "relation_chunk_id": str(rel.chunk_id) if rel.chunk_id is not None else None,
            "relation_event_id": str(rel.event_id) if rel.event_id is not None else None,
            "step": f"hop-{hop + 1}",
        },
    )


def _filter_skill_neighbors(
    neighbors: list[tuple[str, float]],
    *,
    include_skills: bool,
    entity_repo: EntityRepository,
    tenant_id: object,
) -> list[tuple[str, float]]:
    if include_skills or not neighbors:
        return neighbors
    try:
        neighbor_ids = [entity_id for entity_id, _weight in neighbors]
        objs = entity_repo.get_entities_by_ids(neighbor_ids, tenant_id=tenant_id)
        allowed_ids = {str(obj.id) for obj in (objs or []) if not _is_skill_type(obj.type)}
        return [(entity_id, weight) for entity_id, weight in neighbors if entity_id in allowed_ids]
    except Exception as exc:
        logger.debug("Failed to filter KG expansion skill-like neighbors: %s", exc)
        return neighbors


def _extend_seed_entities_with_relations(
    *,
    config: SearchConfig,
    tracker: Tracker,
    relation_repo: RelationRepository,
    entity_repo: EntityRepository,
    tenant_id: object,
    seed_entities: list[str],
    entity_weights: dict[str, float],
    include_skills: bool,
    hop: int,
) -> None:
    if not _relation_expansion_enabled(config) or not seed_entities:
        return
    max_neighbors = max(0, int(settings.KG_SEARCH_RELATION_MAX_NEIGHBORS))
    if max_neighbors <= 0:
        return
    tenant_uuid = _tenant_uuid(tenant_id)
    if tenant_uuid is None:
        return
    min_confidence = float(settings.KG_SEARCH_RELATION_MIN_CONFIDENCE)
    max_edges = max(0, int(settings.KG_SEARCH_RELATION_MAX_EDGES)) or 500
    weight_factor = float(settings.KG_SEARCH_RELATION_NEIGHBOR_WEIGHT_FACTOR)
    bucket_low = float(settings.KG_SEARCH_RELATION_CONF_BUCKET_LOW_MAX)
    bucket_mid = float(settings.KG_SEARCH_RELATION_CONF_BUCKET_MID_MAX)
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
    neighbor_weights: dict[str, float] = {}
    for rel in rel_rows:
        candidate = _relation_neighbor_candidate(
            rel,
            seed_set=seed_set,
            entity_weights=entity_weights,
            weight_factor=weight_factor,
        )
        if candidate is None:
            continue
        from_id, to_id, predicate, confidence, pred_mult, evidence_mult, evidence_source, weight = candidate
        neighbor_weights[to_id] = max(neighbor_weights.get(to_id, 0.0), weight)
        _add_relation_clue(
            tracker,
            rel=rel,
            hop=hop,
            from_id=from_id,
            to_id=to_id,
            predicate=predicate,
            confidence=confidence,
            pred_mult=pred_mult,
            evidence_mult=evidence_mult,
            evidence_source=evidence_source,
            bucket_low=bucket_low,
            bucket_mid=bucket_mid,
        )
    neighbors = sorted(neighbor_weights.items(), key=lambda item: item[1], reverse=True)[:max_neighbors]
    for entity_id, weight in _filter_skill_neighbors(
        neighbors,
        include_skills=include_skills,
        entity_repo=entity_repo,
        tenant_id=tenant_id,
    ):
        if entity_id not in seed_set:
            seed_set.add(entity_id)
            seed_entities.append(entity_id)
        entity_weights[entity_id] = max(entity_weights.get(entity_id, 0.0), weight)


def _record_new_events(
    events: list["KgSourceEvent"],
    *,
    discovered_event_ids: set[str],
    event_hops: dict[str, int],
    hop: int,
) -> list[str]:
    new_event_ids: list[str] = []
    hop_len = 2 + int(hop or 0)
    for event in events:
        event_id = str(event.id)
        if event_id in discovered_event_ids:
            continue
        discovered_event_ids.add(event_id)
        new_event_ids.append(event_id)
        prev = event_hops.get(event_id)
        if prev is None or hop_len < int(prev or 0):
            event_hops[event_id] = int(hop_len)
    return new_event_ids


def _update_event_scores(
    recall_result: RecallResult,
    *,
    events: list["KgSourceEvent"],
    assoc_map: dict[str, list["KgEntity"]],
    entity_weights: dict[str, float],
) -> None:
    for event in events:
        event_id = str(event.id)
        base = recall_result.event_scores.get(event_id, 0.0)
        boost = sum(entity_weights.get(str(entity.id), 0.0) for entity in assoc_map.get(event_id, []))
        recall_result.event_scores[event_id] = base * 0.5 + boost * 0.5


def _collect_new_entities(
    *,
    assoc_map: dict[str, list["KgEntity"]],
    known_entities: set[str],
    include_skills: bool,
    event_scores: dict[str, float],
    tracker: Tracker,
    events_by_id: dict[str, "KgSourceEvent"],
    hop: int,
) -> dict[str, float]:
    new_entities: dict[str, float] = {}
    for event_id, entities in assoc_map.items():
        for entity in entities:
            entity_id = str(entity.id)
            if entity_id in known_entities:
                continue
            if not include_skills and _is_skill_type(entity.type):
                continue
            new_entities[entity_id] = new_entities.get(entity_id, 0.0) + event_scores.get(event_id, 0.0)
            tracker.add_clue(
                stage=f"expand-hop-{hop + 1}",
                from_node=build_event_node(
                    events_by_id.get(event_id) or {"id": event_id},
                    stage=f"expand-hop-{hop + 1}",
                    hop=hop + 1,
                ),
                to_node=build_entity_node(
                    {"entity_id": entity_id, "name": entity.name, "type": entity.type, "hop": hop + 1}
                ),
                confidence=0.3,
                relation="event->entity",
                metadata={"step": f"hop-{hop + 1}"},
            )
    return new_entities


def _build_key_final(
    entity_repo: EntityRepository,
    *,
    tenant_id: object,
    known_entities: set[str],
    include_skills: bool,
    entity_weights: dict[str, float],
    limit: int,
) -> list[dict[str, Any]]:
    key_final: list[dict[str, Any]] = []
    ent_objects = entity_repo.get_entities_by_ids(list(known_entities), tenant_id=tenant_id)
    for entity in ent_objects:
        if not include_skills and _is_skill_type(entity.type):
            continue
        key_final.append(
            {
                "entity_id": str(entity.id),
                "name": entity.name,
                "type": entity.type,
                "weight": entity_weights.get(str(entity.id), 0.0),
            }
        )
    key_final.sort(key=lambda item: item["weight"], reverse=True)
    return key_final[:limit]


def _run_expand_hop(
    *,
    config: SearchConfig,
    recall_result: RecallResult,
    tracker: Tracker,
    relation_repo: RelationRepository,
    entity_repo: EntityRepository,
    event_repo: EventRepository,
    tenant_id: object,
    include_skills: bool,
    max_candidates: int,
    state: _ExpandState,
    hop: int,
) -> bool:
    if not state.current_entities:
        return False
    if max_candidates > 0 and len(state.discovered_event_ids) >= max_candidates:
        return False

    limit = _resolve_expand_limit(
        config,
        discovered_count=len(state.discovered_event_ids),
        max_candidates=max_candidates,
    )
    if limit <= 0:
        return False

    seed_entities = list(state.current_entities)
    _extend_seed_entities_with_relations(
        config=config,
        tracker=tracker,
        relation_repo=relation_repo,
        entity_repo=entity_repo,
        tenant_id=tenant_id,
        seed_entities=seed_entities,
        entity_weights=state.entity_weights,
        include_skills=include_skills,
        hop=hop,
    )
    events = event_repo.find_events_by_entities(
        seed_entities,
        tenant_id=tenant_id,
        limit=limit,
        document_ids=config.document_ids,
        dataset_id=config.dataset_id,
        account_id=config.account_id,
    )
    new_event_ids = _record_new_events(
        events,
        discovered_event_ids=state.discovered_event_ids,
        event_hops=state.event_hops,
        hop=hop,
    )
    if not new_event_ids:
        return False
    state.discovered_events.extend(new_event_ids)
    if max_candidates > 0 and len(state.discovered_event_ids) >= max_candidates:
        return False

    assoc_map = event_repo.get_entities_for_events(new_event_ids, tenant_id=tenant_id)
    _update_event_scores(
        recall_result,
        events=events,
        assoc_map=assoc_map,
        entity_weights=state.entity_weights,
    )
    new_entities = _collect_new_entities(
        assoc_map=assoc_map,
        known_entities=state.known_entities,
        include_skills=include_skills,
        event_scores=recall_result.event_scores,
        tracker=tracker,
        events_by_id={str(event.id): event for event in events},
        hop=hop,
    )
    sorted_new = sorted(new_entities.items(), key=lambda item: item[1], reverse=True)[: config.expand.entities_per_hop]
    if not sorted_new:
        return False

    state.current_entities = []
    for entity_id, weight in sorted_new:
        state.known_entities.add(entity_id)
        state.entity_weights[entity_id] = state.entity_weights.get(entity_id, 0.0) * 0.5 + weight * 0.5
        state.current_entities.append(entity_id)

    min_events = int(config.expand.min_events_per_hop or 0)
    return not (min_events > 0 and len(new_event_ids) < min_events)


def _run_expand_hops(
    *,
    config: SearchConfig,
    recall_result: RecallResult,
    tracker: Tracker,
    relation_repo: RelationRepository,
    entity_repo: EntityRepository,
    event_repo: EventRepository,
    tenant_id: object,
    include_skills: bool,
    max_candidates: int,
    state: _ExpandState,
) -> None:
    for hop in range(config.expand.max_hops):
        if not _run_expand_hop(
            config=config,
            recall_result=recall_result,
            tracker=tracker,
            relation_repo=relation_repo,
            entity_repo=entity_repo,
            event_repo=event_repo,
            tenant_id=tenant_id,
            include_skills=include_skills,
            max_candidates=max_candidates,
            state=state,
            hop=hop,
        ):
            break


async def expand(config: SearchConfig, recall_result: RecallResult) -> ExpandResult:
    return await asyncio.to_thread(_expand_sync, config, recall_result)


def _expand_sync(config: SearchConfig, recall_result: RecallResult) -> ExpandResult:
    if config.document_ids is not None and not config.document_ids:
        return _empty_scope_result(recall_result)
    if not config.expand.enabled:
        return _disabled_expand_result(recall_result)

    tracker = Tracker()
    tracker.extend_clues(list(recall_result.clues or []))
    session = get_session()
    try:
        entity_repo = EntityRepository(session)
        event_repo = EventRepository(session)
        relation_repo = RelationRepository(session)
        tenant_id = config.tenant_id or settings.DEFAULT_TENANT_ID
        include_skills = bool(config.include_skill_entities)
        state = _build_expand_state(recall_result, include_skills=include_skills)
        max_candidates = max(0, int(settings.KG_SEARCH_MAX_RERANK_CANDIDATES))
        _run_expand_hops(
            config=config,
            recall_result=recall_result,
            tracker=tracker,
            relation_repo=relation_repo,
            entity_repo=entity_repo,
            event_repo=event_repo,
            tenant_id=tenant_id,
            include_skills=include_skills,
            max_candidates=max_candidates,
            state=state,
        )

        return ExpandResult(
            key_final=_build_key_final(
                entity_repo,
                tenant_id=tenant_id,
                known_entities=state.known_entities,
                include_skills=include_skills,
                entity_weights=state.entity_weights,
                limit=config.recall.final_entity_count,
            ),
            event_ids=state.discovered_events,
            clues=tracker.get_clues(),
            event_scores=recall_result.event_scores,
            event_hops=state.event_hops,
        )
    finally:
        session.close()
