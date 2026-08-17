"""
Recall stage: 8-step pipeline (query -> keys -> events -> weights).
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.rag.kg.loading.processor import DocumentProcessor
from app.rag.kg.repository import AliasRepository, EntityRepository, EventRepository, RelationRepository, get_session
from app.rag.kg.search import graph_embeddings as graph_embeddings_mod
from app.rag.kg.search.config import SearchConfig
from app.rag.kg.search.query_mode import build_mode_aware_recall_overrides, normalize_kg_query_mode
from app.rag.kg.search.relation_scoring import relation_multiplier
from app.rag.kg.search.tracker import Tracker
from app.rag.kg.search.utils import confidence_bucket, cosine_similarity

logger = get_logger(__name__)

_SKILL_TYPES = {"Skill", "SkillTag", "SkillCategory"}


@dataclass
class RecallResult:
    query_vector: list[float]
    key_final: list[dict[str, Any]]
    event_ids: list[str]
    clues: list[dict[str, Any]]
    key_weights: dict[str, float]
    event_scores: dict[str, float]
    # Stable per-event hop/path-length estimates for downstream ranking signals.
    event_hops: dict[str, int] = field(default_factory=dict)
    relation_debug: dict[str, Any] = field(default_factory=dict)
    serving_layer: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ServingLayerBudgetResult:
    event_ids: list[str]
    kept: int
    dropped: int
    dropped_by_score: int = 0
    dropped_by_chunk: int = 0
    dropped_by_document: int = 0
    reason: str = "applied"


@dataclass(frozen=True)
class _RecallLimits:
    mode_norm: str
    mode_overrides: dict[str, Any]
    mode_reason_codes: list[str]
    prefer_lexical_first: bool
    max_entities: int
    final_entity_count: int
    entity_weight_threshold: float
    target_max_events: int
    candidate_max_events: int
    serving_enabled: bool
    serving_candidate_multiplier: int
    vector_recall_enabled: bool


@dataclass(frozen=True)
class _GraphEmbeddingSettings:
    enabled: bool
    max_events: int
    max_entities: int
    max_relations: int
    top_k: int
    min_similarity: float


def _event_id(value: Any) -> str:
    return str(getattr(value, "id", "") or "").strip()


def _scope_key(value: Any, field_name: str, *, fallback: str) -> str:
    raw = getattr(value, field_name, None)
    key = str(raw or "").strip()
    return key or fallback


def apply_serving_layer_budget(
    events: list[Any],
    event_scores: dict[str, float],
    *,
    enabled: bool,
    max_events_per_chunk: int,
    max_events_per_document: int,
    min_score: float,
    bypass: bool,
) -> ServingLayerBudgetResult:
    """
    Keep online KG search on a high-value serving subset.

    Full KG extraction/storage remains unchanged. This budget only trims the
    recall candidates that continue into expand/rerank, which prevents one long
    document or noisy chunk from dominating normal RAG latency.
    """
    event_list = [event for event in (events or []) if _event_id(event)]
    if not event_list:
        return ServingLayerBudgetResult(event_ids=[], kept=0, dropped=0, reason="empty")

    event_list.sort(key=lambda ev: (-float(event_scores.get(_event_id(ev), 0.0) or 0.0), _event_id(ev)))
    if not enabled:
        event_ids = [_event_id(ev) for ev in event_list]
        return ServingLayerBudgetResult(event_ids=event_ids, kept=len(event_ids), dropped=0, reason="disabled")
    if bypass:
        event_ids = [_event_id(ev) for ev in event_list]
        return ServingLayerBudgetResult(event_ids=event_ids, kept=len(event_ids), dropped=0, reason="bypassed")

    per_chunk_limit = max(0, int(max_events_per_chunk or 0))
    per_doc_limit = max(0, int(max_events_per_document or 0))
    score_floor = max(0.0, float(min_score or 0.0))

    kept_ids: list[str] = []
    chunk_counts: dict[str, int] = {}
    doc_counts: dict[str, int] = {}
    dropped_by_score = 0
    dropped_by_chunk = 0
    dropped_by_document = 0

    for event in event_list:
        eid = _event_id(event)
        score = float(event_scores.get(eid, 0.0) or 0.0)
        if score < score_floor:
            dropped_by_score += 1
            continue

        chunk_key = _scope_key(event, "chunk_id", fallback=f"event:{eid}")
        if per_chunk_limit and int(chunk_counts.get(chunk_key, 0) or 0) >= per_chunk_limit:
            dropped_by_chunk += 1
            continue

        doc_key = _scope_key(event, "document_id", fallback=f"event:{eid}")
        if per_doc_limit and int(doc_counts.get(doc_key, 0) or 0) >= per_doc_limit:
            dropped_by_document += 1
            continue

        kept_ids.append(eid)
        chunk_counts[chunk_key] = int(chunk_counts.get(chunk_key, 0) or 0) + 1
        doc_counts[doc_key] = int(doc_counts.get(doc_key, 0) or 0) + 1

    dropped = dropped_by_score + dropped_by_chunk + dropped_by_document
    return ServingLayerBudgetResult(
        event_ids=kept_ids,
        kept=len(kept_ids),
        dropped=dropped,
        dropped_by_score=dropped_by_score,
        dropped_by_chunk=dropped_by_chunk,
        dropped_by_document=dropped_by_document,
    )


def _should_bypass_serving_layer(*, mode: str, reason_codes: list[str]) -> bool:
    reasons = {str(item or "").strip() for item in (reason_codes or []) if str(item or "").strip()}
    if str(mode or "").strip().lower() == "drift":
        return True
    return bool({"global_pattern", "drift_pattern"} & reasons)


def _empty_scope_result() -> RecallResult:
    return RecallResult(
        query_vector=[],
        key_final=[],
        event_ids=[],
        clues=[],
        key_weights={},
        event_scores={},
        event_hops={},
        relation_debug={"enabled": False, "reason": "empty_document_scope"},
        serving_layer={"enabled": False, "reason": "empty_document_scope"},
    )


def _tenant_uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except Exception:
        return None


def _query_reason_codes(config: SearchConfig) -> set[str]:
    return {str(item).strip() for item in (getattr(config, "query_mode_reason_codes", []) or []) if str(item).strip()}


def _prefer_lexical_first(
    config: SearchConfig,
    *,
    mode_norm: str,
    mode_reason_codes: list[str],
    query_reason_codes: set[str],
) -> bool:
    if config.dataset_id is None and config.document_ids is None:
        return False
    if "low_confidence_global_budget" in set(mode_reason_codes):
        return True
    return str(mode_norm) == "local" and bool({"dataset_factoid_scope", "quoted_term"} & query_reason_codes)


def _vector_recall_enabled(config: SearchConfig) -> bool:
    if getattr(config, "vector_recall_enabled", None) is not None:
        return bool(config.vector_recall_enabled)
    return bool(getattr(settings, "KG_SEARCH_VECTOR_RECALL_ENABLED", True))


def _build_recall_limits(config: SearchConfig) -> _RecallLimits:
    mode_norm = normalize_kg_query_mode(getattr(config, "query_mode", "auto"), default="global")
    mode_overrides = build_mode_aware_recall_overrides(
        mode=mode_norm,
        max_events=int(config.recall.max_events),
        max_entities=int(config.recall.max_entities),
        final_entity_count=int(config.recall.final_entity_count),
        entity_weight_threshold=float(config.recall.entity_weight_threshold),
        query_mode_confidence=getattr(config, "query_mode_confidence", None),
        query_mode_reason_codes=list(getattr(config, "query_mode_reason_codes", []) or []),
    )
    mode_reason_codes = [str(item) for item in (mode_overrides.get("reason_codes") or []) if str(item).strip()]
    max_events = int(mode_overrides.get("max_events") or config.recall.max_events)
    max_candidates = max(0, int(getattr(settings, "KG_SEARCH_MAX_RERANK_CANDIDATES", 0) or 0))
    if max_candidates > 0:
        max_events = min(max_events, max_candidates)
    target_max_events = max(1, int(max_events or 1))
    serving_enabled = bool(getattr(settings, "KG_SEARCH_SERVING_LAYER_ENABLED", True))
    serving_candidate_multiplier = max(1, int(getattr(settings, "KG_SEARCH_SERVING_CANDIDATE_MULTIPLIER", 3) or 3))
    candidate_max_events = target_max_events
    if serving_enabled:
        candidate_max_events = target_max_events * serving_candidate_multiplier
        if max_candidates > 0:
            candidate_max_events = min(candidate_max_events, max_candidates)
        candidate_max_events = max(target_max_events, candidate_max_events)
    return _RecallLimits(
        mode_norm=str(mode_norm),
        mode_overrides=mode_overrides,
        mode_reason_codes=mode_reason_codes,
        prefer_lexical_first=_prefer_lexical_first(
            config,
            mode_norm=str(mode_norm),
            mode_reason_codes=mode_reason_codes,
            query_reason_codes=_query_reason_codes(config),
        ),
        max_entities=int(mode_overrides.get("max_entities") or config.recall.max_entities),
        final_entity_count=int(mode_overrides.get("final_entity_count") or config.recall.final_entity_count),
        entity_weight_threshold=float(
            mode_overrides.get("entity_weight_threshold") or config.recall.entity_weight_threshold
        ),
        target_max_events=target_max_events,
        candidate_max_events=candidate_max_events,
        serving_enabled=serving_enabled,
        serving_candidate_multiplier=serving_candidate_multiplier,
        vector_recall_enabled=_vector_recall_enabled(config),
    )


def _match_alias_hits(
    alias_repo: AliasRepository,
    *,
    query: str,
    tenant_id: object,
    max_entities: int,
) -> list[dict[str, Any]]:
    try:
        return alias_repo.match_aliases(
            query=query,
            tenant_id=tenant_id,
            limit=max(0, int(max_entities)),
        )
    except Exception:
        return []


def _expand_query_with_alias_hits(query: str, alias_hits: list[dict[str, Any]]) -> str:
    expanded_query = str(query or "")
    if not alias_hits:
        return expanded_query
    names_added = 0
    expanded_fold = expanded_query.casefold()
    for hit in alias_hits[:5]:
        name = str((hit or {}).get("name") or "").strip()
        if not name:
            continue
        if name.isascii() and name.casefold() in expanded_fold:
            continue
        if not name.isascii() and name in expanded_query:
            continue
        expanded_query = f"{expanded_query} {name}".strip()
        names_added += 1
        if names_added >= 5:
            break
    return expanded_query


def _lexical_first_event_results(
    event_repo: EventRepository,
    *,
    config: SearchConfig,
    tenant_id: object,
    enabled: bool,
) -> list[dict[str, Any]]:
    if not enabled:
        return []
    try:
        return event_repo.search_events_lexical(
            query=str(config.query or ""),
            tenant_id=tenant_id,
            k=config.recall.vector_candidates,
            document_ids=config.document_ids,
            dataset_id=config.dataset_id,
            account_id=config.account_id,
        )
    except Exception:
        return []


async def _query_embedding(processor: DocumentProcessor, expanded_query: str) -> list[float]:
    try:
        return await processor.generate_embedding(expanded_query)
    except Exception:
        return []


def _vector_entity_hits(
    entity_repo: EntityRepository,
    *,
    query_vec: list[float],
    tenant_id: object,
    vector_candidates: int,
) -> list[dict[str, Any]]:
    if not query_vec:
        return []
    try:
        return entity_repo.search_similar(
            query_vector=query_vec,
            tenant_id=tenant_id,
            k=vector_candidates,
        )
    except Exception:
        return []


def _merge_alias_hits(
    tracker: Tracker,
    *,
    config: SearchConfig,
    raw_entities: list[dict[str, Any]],
    alias_hits: list[dict[str, Any]],
) -> set[str]:
    alias_key_ids: set[str] = set()
    existing_ids = {str((item or {}).get("entity_id") or "").strip() for item in (raw_entities or [])}
    for hit in alias_hits:
        entity_id = str((hit or {}).get("entity_id") or "").strip()
        if not entity_id:
            continue
        alias_key_ids.add(entity_id)
        if entity_id in existing_ids:
            continue
        raw_entities.append(hit)
        existing_ids.add(entity_id)
        tracker.add_clue(
            stage="recall",
            from_node=Tracker.build_query_node(config),
            to_node=Tracker.build_entity_node(hit),
            confidence=float((hit or {}).get("similarity", 1.0) or 1.0),
            relation="query->entity:alias",
            metadata={"method": "alias_match", "step": "step0"},
        )
    return alias_key_ids


def _lexical_entity_fallback(
    tracker: Tracker,
    entity_repo: EntityRepository,
    *,
    config: SearchConfig,
    tenant_id: object,
    raw_entities: list[dict[str, Any]],
    alias_hits: list[dict[str, Any]],
    max_entities: int,
) -> None:
    if raw_entities or alias_hits:
        return
    try:
        lexical_entities = entity_repo.search_lexical(
            query=str(config.query or ""),
            tenant_id=tenant_id,
            k=max_entities,
            document_ids=config.document_ids,
            dataset_id=config.dataset_id,
            account_id=config.account_id,
        )
    except Exception:
        lexical_entities = []
    if not lexical_entities:
        return
    raw_entities.extend(lexical_entities)
    for hit in lexical_entities[: max(1, int(max_entities))]:
        tracker.add_clue(
            stage="recall",
            from_node=Tracker.build_query_node(config),
            to_node=Tracker.build_entity_node(hit),
            confidence=float((hit or {}).get("similarity", 0.0) or 0.0),
            relation="query->entity:lexical",
            metadata={"method": "lexical_match", "step": "step1-fallback"},
        )


def _graph_embedding_settings(config: SearchConfig) -> _GraphEmbeddingSettings:
    if getattr(config, "graph_embeddings_enabled", None) is not None:
        enabled = bool(config.graph_embeddings_enabled)
    else:
        enabled = bool(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_ENABLED", False))
    return _GraphEmbeddingSettings(
        enabled=enabled,
        max_events=max(0, int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_MAX_EVENTS", 200) or 200)),
        max_entities=max(0, int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_MAX_ENTITIES", 400) or 400)),
        max_relations=max(0, int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_MAX_RELATIONS", 1500) or 1500)),
        top_k=max(0, int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_TOP_K", 20) or 20)),
        min_similarity=float(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_MIN_SIMILARITY", 0.35) or 0.35),
    )


def _graph_seed_maps(
    alias_key_ids: set[str],
    raw_entities: list[dict[str, Any]],
) -> tuple[list[str], list[str], set[str], dict[str, dict[str, Any]]]:
    seed_entity_ids = sorted({str(entity_id) for entity_id in alias_key_ids if str(entity_id).strip()})
    existing_ids = {str((item or {}).get("entity_id") or "").strip() for item in (raw_entities or [])}
    seed_entity_map = {
        str((item or {}).get("entity_id") or "").strip(): item
        for item in (raw_entities or [])
        if str((item or {}).get("entity_id") or "").strip()
    }
    return seed_entity_ids, [f"ent:{entity_id}" for entity_id in seed_entity_ids], existing_ids, seed_entity_map


def _graph_kept_entity_ids(
    seed_entity_ids: list[str],
    assoc_map: dict[Any, list[Any]],
    *,
    max_entities: int,
) -> set[str]:
    entity_counts: dict[str, int] = {}
    for links in (assoc_map or {}).values():
        for link in links or []:
            entity_id = str(getattr(link, "entity_id", "") or "").strip()
            if not entity_id:
                continue
            entity_counts[entity_id] = int(entity_counts.get(entity_id, 0) or 0) + 1
    kept_entity_ids: set[str] = set(seed_entity_ids)
    if max_entities <= 0 or len(kept_entity_ids) >= max_entities:
        return kept_entity_ids
    ranked = sorted(
        [(entity_id, int(entity_counts.get(entity_id, 0) or 0)) for entity_id in entity_counts.keys()],
        key=lambda item: (-int(item[1]), str(item[0])),
    )
    for entity_id, _count in ranked:
        if len(kept_entity_ids) >= max_entities:
            break
        kept_entity_ids.add(str(entity_id))
    return kept_entity_ids


def _graph_relation_edges(
    session: Any,
    *,
    config: SearchConfig,
    tenant_uuid: UUID | None,
    kept_entity_ids: set[str],
    max_relations: int,
) -> list[tuple[str, str]]:
    if tenant_uuid is None or max_relations <= 0 or not kept_entity_ids:
        return []
    if not bool(getattr(settings, "KG_RELATION_ENABLED", False)):
        return []
    try:
        min_conf = float(getattr(settings, "KG_SEARCH_RELATION_MIN_CONFIDENCE", 0.0) or 0.0)
    except Exception:
        min_conf = 0.0
    ent_list = sorted(kept_entity_ids)[: min(len(kept_entity_ids), 300)]
    try:
        rel_rows = RelationRepository(session).list_relations_for_entities(
            ent_list,
            tenant_id=tenant_uuid,
            document_ids=config.document_ids,
            dataset_id=config.dataset_id,
            account_id=config.account_id,
            min_confidence=min_conf if min_conf > 0 else None,
            limit=max_relations,
        )
    except Exception:
        rel_rows = []
    relation_edges: list[tuple[str, str]] = []
    ordered_rows = sorted(
        rel_rows or [],
        key=lambda row: (
            str(getattr(row, "subject_entity_id", "") or ""),
            str(getattr(row, "predicate", "") or ""),
            str(getattr(row, "object_entity_id", "") or ""),
            str(getattr(row, "id", "") or ""),
        ),
    )
    for rel in ordered_rows:
        subject_id = str(getattr(rel, "subject_entity_id", "") or "").strip()
        object_id = str(getattr(rel, "object_entity_id", "") or "").strip()
        if not subject_id or not object_id:
            continue
        if subject_id not in kept_entity_ids or object_id not in kept_entity_ids:
            continue
        relation_edges.append((subject_id, object_id))
    return relation_edges


def _graph_candidate_hits(
    hits: list[dict[str, Any]],
    *,
    existing_ids: set[str],
) -> tuple[list[str], dict[str, str], dict[str, float]]:
    candidate_entity_ids: list[str] = []
    hit_seed_by_entity: dict[str, str] = {}
    hit_sim_by_entity: dict[str, float] = {}
    for hit in hits or []:
        node_key = str(hit.get("node_key") or "")
        seed_key = str(hit.get("seed_node_key") or "")
        if not node_key.startswith("ent:"):
            continue
        entity_id = node_key.split(":", 1)[1]
        if not entity_id or entity_id in existing_ids:
            continue
        candidate_entity_ids.append(entity_id)
        if seed_key.startswith("ent:"):
            hit_seed_by_entity[entity_id] = seed_key.split(":", 1)[1]
        try:
            hit_sim_by_entity[entity_id] = float(hit.get("similarity", 0.0) or 0.0)
        except Exception:
            hit_sim_by_entity[entity_id] = 0.0
    return candidate_entity_ids, hit_seed_by_entity, hit_sim_by_entity


def _append_graph_entities(
    tracker: Tracker,
    entity_repo: EntityRepository,
    *,
    tenant_uuid: UUID | None,
    tenant_id: object,
    raw_entities: list[dict[str, Any]],
    existing_ids: set[str],
    candidate_entity_ids: list[str],
    hit_seed_by_entity: dict[str, str],
    hit_sim_by_entity: dict[str, float],
    seed_entity_map: dict[str, dict[str, Any]],
) -> None:
    if not candidate_entity_ids:
        return
    ents = entity_repo.get_entities_by_ids(candidate_entity_ids, tenant_id=tenant_uuid)
    ent_by_id = {str(getattr(entity, "id", "") or ""): entity for entity in (ents or [])}
    for entity_id in candidate_entity_ids:
        if entity_id in existing_ids:
            continue
        obj = ent_by_id.get(str(entity_id))
        if obj is None:
            continue
        similarity = float(hit_sim_by_entity.get(entity_id, 0.0) or 0.0)
        ent_dict = {
            "entity_id": str(entity_id),
            "name": str(getattr(obj, "name", "") or ""),
            "type": str(getattr(obj, "type", "") or "unknown"),
            "similarity": similarity,
            "tenant_id": str(tenant_id),
            "method": "graph_embedding",
        }
        raw_entities.append(ent_dict)
        existing_ids.add(str(entity_id))
        seed_id = str(hit_seed_by_entity.get(entity_id, "") or "").strip()
        if not seed_id:
            continue
        tracker.add_clue(
            stage="recall",
            from_node=Tracker.build_entity_node(
                seed_entity_map.get(seed_id) or {"entity_id": seed_id, "name": "", "type": "unknown"}
            ),
            to_node=Tracker.build_entity_node(ent_dict),
            confidence=similarity,
            relation="entity->entity:graph_embedding",
            metadata={"method": "graph_embedding", "step": "step1b"},
        )


def _apply_graph_embedding_recall(
    tracker: Tracker,
    session: Any,
    entity_repo: EntityRepository,
    event_repo: EventRepository,
    *,
    config: SearchConfig,
    tenant_id: object,
    alias_key_ids: set[str],
    vector_recall_enabled: bool,
    query_vec: list[float],
    raw_entities: list[dict[str, Any]],
) -> None:
    graph_settings = _graph_embedding_settings(config)
    if not graph_settings.enabled or not alias_key_ids:
        return
    if vector_recall_enabled and query_vec:
        return
    try:
        tenant_uuid = _tenant_uuid(tenant_id)
        if tenant_uuid is None:
            return
        if graph_settings.top_k <= 0 or graph_settings.max_events <= 0 or graph_settings.max_entities <= 0:
            return
        seed_entity_ids, seed_nodes, existing_ids, seed_entity_map = _graph_seed_maps(alias_key_ids, raw_entities)
        event_ids = event_repo.search_events_by_entities(
            seed_entity_ids,
            tenant_id=tenant_id,
            limit=graph_settings.max_events,
            document_ids=config.document_ids,
            dataset_id=config.dataset_id,
            account_id=config.account_id,
        )
        event_id_strs = [str(event_id) for event_id in (event_ids or []) if event_id is not None]
        assoc_map = event_repo.get_event_entities(event_ids or [], tenant_id=tenant_uuid)
        kept_entity_ids = _graph_kept_entity_ids(
            seed_entity_ids,
            assoc_map,
            max_entities=graph_settings.max_entities,
        )
        adjacency = graph_embeddings_mod.build_entity_event_adjacency(
            seed_entity_ids=seed_entity_ids,
            event_ids=event_id_strs,
            event_entity_links={str(key): list(value or []) for key, value in (assoc_map or {}).items()},
            kept_entity_ids=kept_entity_ids,
            relation_edges=_graph_relation_edges(
                session,
                config=config,
                tenant_uuid=tenant_uuid,
                kept_entity_ids=kept_entity_ids,
                max_relations=graph_settings.max_relations,
            ),
        )
        params = graph_embeddings_mod.WalkHashParams(
            dim=int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_DIM", 64) or 64),
            num_walks=int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_NUM_WALKS", 8) or 8),
            walk_length=int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_WALK_LENGTH", 20) or 20),
            window_size=int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_WINDOW_SIZE", 5) or 5),
            seed=int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_SEED", 42) or 42),
        )
        hits = graph_embeddings_mod.recall_similar_entity_nodes(
            adjacency=adjacency,
            seed_entity_node_keys=seed_nodes,
            params=params,
            top_k=graph_settings.top_k,
            min_similarity=graph_settings.min_similarity,
            entity_prefix="ent:",
        )
        candidate_entity_ids, hit_seed_by_entity, hit_sim_by_entity = _graph_candidate_hits(
            hits,
            existing_ids=existing_ids,
        )
        _append_graph_entities(
            tracker,
            entity_repo,
            tenant_uuid=tenant_uuid,
            tenant_id=tenant_id,
            raw_entities=raw_entities,
            existing_ids=existing_ids,
            candidate_entity_ids=candidate_entity_ids,
            hit_seed_by_entity=hit_seed_by_entity,
            hit_sim_by_entity=hit_sim_by_entity,
            seed_entity_map=seed_entity_map,
        )
    except Exception as exc:
        logger.debug("Graph embedding recall failed; continuing KG search without it: %s", exc)


def _filter_skill_entities(raw_entities: list[dict[str, Any]], *, include_skill_entities: bool) -> list[dict[str, Any]]:
    if include_skill_entities:
        return list(raw_entities or [])
    return [item for item in (raw_entities or []) if str((item or {}).get("type") or "").strip() not in _SKILL_TYPES]


def _filter_entities_to_scope(
    event_repo: EventRepository,
    *,
    config: SearchConfig,
    tenant_id: object,
    raw_entities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not raw_entities or (config.document_ids is None and config.dataset_id is None):
        return raw_entities
    candidate_ids = [item.get("entity_id") or item.get("id") for item in raw_entities]
    allowed_entity_ids: set[UUID] | None = None
    if config.document_ids is not None:
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
    if allowed_entity_ids is None:
        return raw_entities
    filtered_entities: list[dict[str, Any]] = []
    for ent in raw_entities:
        entity_id = ent.get("entity_id") or ent.get("id")
        if entity_id is None:
            continue
        try:
            entity_uuid = UUID(str(entity_id))
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if entity_uuid in allowed_entity_ids:
            filtered_entities.append(ent)
    return filtered_entities


def _key_query_related(
    raw_entities: list[dict[str, Any]],
    *,
    threshold: float,
    max_entities: int,
) -> list[dict[str, Any]]:
    return [item for item in raw_entities if item.get("similarity", 0.0) >= threshold][:max_entities]


def _record_query_entity_clues(
    tracker: Tracker,
    *,
    config: SearchConfig,
    key_query_related: list[dict[str, Any]],
) -> None:
    for ent in key_query_related:
        tracker.add_clue(
            stage="recall",
            from_node=Tracker.build_query_node(config),
            to_node=Tracker.build_entity_node(ent),
            confidence=ent.get("similarity", 0.0),
            relation="query->entity",
            metadata={"method": "vector_search", "step": "step1"},
        )


def _normalize_key_weights(key_query_related: list[dict[str, Any]]) -> dict[str, float]:
    key_weights: dict[str, float] = {}
    if not key_query_related:
        return key_weights
    sims = [item.get("similarity", 0.0) for item in key_query_related]
    max_sim = max(sims) or 1.0
    for ent in key_query_related:
        key_weights[ent["entity_id"]] = ent.get("similarity", 0.0) / max_sim
    return key_weights


def _base_relation_debug(mode_norm: str, mode_overrides: dict[str, Any]) -> dict[str, Any]:
    reason_codes = [str(item) for item in (mode_overrides.get("reason_codes") or []) if str(item).strip()]
    return {
        "enabled": False,
        "query_mode": str(mode_norm),
        "query_mode_reason_codes": reason_codes[:8],
    }


def _relation_expansion_enabled(config: SearchConfig) -> bool:
    if config.relation_expansion_enabled is not None:
        return bool(config.relation_expansion_enabled)
    return bool(getattr(settings, "KG_SEARCH_RELATION_EXPANSION_ENABLED", False)) and bool(
        getattr(settings, "KG_RELATION_ENABLED", False)
    )


def _relation_direction(rel: Any, weighted_entity_ids: set[str]) -> tuple[str | None, str | None, str | None]:
    subject_id = str(getattr(rel, "subject_entity_id", "") or "")
    object_id = str(getattr(rel, "object_entity_id", "") or "")
    if not subject_id or not object_id:
        return None, None, None
    predicate = str(getattr(rel, "predicate", "") or "").strip()
    if not predicate or predicate.casefold() == "unknown":
        return None, None, None
    if subject_id in weighted_entity_ids:
        return subject_id, object_id, predicate
    if object_id in weighted_entity_ids:
        return object_id, subject_id, predicate
    return None, None, None


def _alias_relation_allowed(rel: Any, *, from_id: str, alias_key_ids: set[str]) -> bool:
    if from_id not in alias_key_ids:
        return True
    refs = getattr(rel, "references", None)
    evidence_quote = str(refs.get("evidence_quote") or "").strip() if isinstance(refs, dict) else ""
    return bool(evidence_quote)


def _relation_evidence(rel: Any) -> tuple[float, str]:
    try:
        refs = getattr(rel, "references", None)
        evidence_source = str(refs.get("evidence_source") or "").strip().casefold() if isinstance(refs, dict) else ""
        if evidence_source != "mention":
            return 1.0, evidence_source
        mention_mult = float(getattr(settings, "KG_SEARCH_RELATION_MENTION_EVIDENCE_MULTIPLIER", 0.7) or 0.7)
        return max(0.0, min(1.0, float(mention_mult))), evidence_source
    except Exception:
        return 1.0, ""


def _relation_candidate(
    rel: Any,
    *,
    key_weights: dict[str, float],
    alias_key_ids: set[str],
    weight_factor: float,
) -> tuple[str, str, str, float, float, float, str, float] | None:
    from_id, to_id, predicate = _relation_direction(rel, set(key_weights))
    if not from_id or not to_id or not predicate or to_id == from_id:
        return None
    if not _alias_relation_allowed(rel, from_id=from_id, alias_key_ids=alias_key_ids):
        return None
    confidence = float(getattr(rel, "confidence", 0.0) or 0.0)
    if confidence <= 0:
        return None
    pred_mult = relation_multiplier(
        predicate,
        from_is_subject=bool(from_id == str(getattr(rel, "subject_entity_id", ""))),
    )
    if pred_mult <= 0:
        return None
    evidence_mult, evidence_source = _relation_evidence(rel)
    weight = float(key_weights.get(from_id, 0.0) or 0.0) * confidence * float(weight_factor) * pred_mult * evidence_mult
    if weight <= 0:
        return None
    return from_id, to_id, predicate, confidence, pred_mult, evidence_mult, evidence_source, weight


def _record_relation_clue(
    tracker: Tracker,
    *,
    key_entity_map: dict[str, dict[str, Any]],
    rel: Any,
    from_id: str,
    to_id: str,
    predicate: str,
    confidence: float,
    pred_mult: float,
    evidence_mult: float,
    evidence_source: str,
    bucket_low: float,
    bucket_mid: float,
) -> str:
    bucket = confidence_bucket(confidence, low_max=bucket_low, mid_max=bucket_mid)
    tracker.add_clue(
        stage="recall",
        from_node=Tracker.build_entity_node(
            key_entity_map.get(from_id) or {"entity_id": from_id, "name": "", "type": "unknown"}
        ),
        to_node=Tracker.build_entity_node({"entity_id": to_id, "name": "", "type": "unknown"}),
        confidence=confidence,
        relation=f"entity->entity:{predicate}" if predicate else "entity->entity",
        metadata={
            "method": "relation_expansion",
            "predicate": predicate,
            "predicate_multiplier": pred_mult,
            "evidence_multiplier": float(evidence_mult),
            "evidence_source": evidence_source,
            "confidence_bucket": bucket,
            "relation_id": str(getattr(rel, "id", "") or "") or None,
            "relation_document_id": str(getattr(rel, "document_id", "") or "") or None,
            "relation_chunk_id": str(getattr(rel, "chunk_id", "") or "") or None,
            "relation_event_id": str(getattr(rel, "event_id", "") or "") or None,
            "step": "step1.5",
        },
    )
    return bucket


def _apply_relation_expansion(
    tracker: Tracker,
    session: Any,
    *,
    config: SearchConfig,
    tenant_id: object,
    mode_norm: str,
    mode_overrides: dict[str, Any],
    key_query_related: list[dict[str, Any]],
    key_weights: dict[str, float],
    alias_key_ids: set[str],
) -> tuple[list[str], dict[str, Any]]:
    relation_debug = _base_relation_debug(mode_norm, mode_overrides)
    if not _relation_expansion_enabled(config) or not key_query_related:
        return [], relation_debug
    max_neighbors = max(0, int(getattr(settings, "KG_SEARCH_RELATION_MAX_NEIGHBORS", 0) or 0))
    if max_neighbors <= 0:
        return [], relation_debug
    tenant_uuid = _tenant_uuid(tenant_id)
    if tenant_uuid is None:
        return [], relation_debug
    min_confidence = float(getattr(settings, "KG_SEARCH_RELATION_MIN_CONFIDENCE", 0.0) or 0.0)
    max_edges = max(0, int(getattr(settings, "KG_SEARCH_RELATION_MAX_EDGES", 0) or 0)) or 500
    weight_factor = float(getattr(settings, "KG_SEARCH_RELATION_NEIGHBOR_WEIGHT_FACTOR", 0.7) or 0.7)
    bucket_low = float(getattr(settings, "KG_SEARCH_RELATION_CONF_BUCKET_LOW_MAX", 0.4) or 0.4)
    bucket_mid = float(getattr(settings, "KG_SEARCH_RELATION_CONF_BUCKET_MID_MAX", 0.7) or 0.7)
    relation_debug.update(
        {
            "enabled": True,
            "min_confidence": float(min_confidence),
            "max_edges": int(max_edges),
            "max_neighbors": int(max_neighbors),
            "weight_factor": float(weight_factor),
            "conf_bucket_low_max": float(bucket_low),
            "conf_bucket_mid_max": float(bucket_mid),
        }
    )
    rel_rows = RelationRepository(session).list_relations_for_entities(
        [item["entity_id"] for item in key_query_related],
        tenant_id=tenant_uuid,
        document_ids=config.document_ids,
        dataset_id=config.dataset_id,
        account_id=config.account_id,
        min_confidence=min_confidence if min_confidence > 0 else None,
        limit=max_edges,
    )
    relation_debug["edges_fetched"] = int(len(rel_rows))
    key_entity_map = {item.get("entity_id"): item for item in key_query_related if item.get("entity_id")}
    neighbor_weights: dict[str, float] = {}
    predicate_hist: dict[str, int] = {}
    conf_bucket_hist: dict[str, int] = {"low": 0, "mid": 0, "high": 0}
    edges_used = 0
    for rel in rel_rows:
        candidate = _relation_candidate(
            rel,
            key_weights=key_weights,
            alias_key_ids=alias_key_ids,
            weight_factor=weight_factor,
        )
        if candidate is None:
            continue
        from_id, to_id, predicate, confidence, pred_mult, evidence_mult, evidence_source, weight = candidate
        bucket = _record_relation_clue(
            tracker,
            key_entity_map=key_entity_map,
            rel=rel,
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
        neighbor_weights[to_id] = max(neighbor_weights.get(to_id, 0.0), weight)
        predicate_hist[predicate] = int(predicate_hist.get(predicate, 0) or 0) + 1
        conf_bucket_hist[bucket] = int(conf_bucket_hist.get(bucket, 0) or 0) + 1
        edges_used += 1
    sorted_neighbors = sorted(neighbor_weights.items(), key=lambda item: item[1], reverse=True)[:max_neighbors]
    for entity_id, weight in sorted_neighbors:
        key_weights[entity_id] = max(key_weights.get(entity_id, 0.0), weight)
    relation_debug["edges_used"] = int(edges_used)
    relation_debug["neighbors_total"] = int(len(neighbor_weights))
    relation_debug["neighbors_selected"] = int(len(sorted_neighbors))
    relation_debug["predicate_hist"] = dict(sorted(predicate_hist.items(), key=lambda item: (-item[1], item[0])))
    relation_debug["confidence_bucket_hist"] = dict(conf_bucket_hist)
    return [entity_id for entity_id, _weight in sorted_neighbors], relation_debug


def _search_events_by_entities(
    event_repo: EventRepository,
    *,
    config: SearchConfig,
    tenant_id: object,
    entity_ids: list[str],
    limit: int,
) -> list[Any]:
    return list(
        event_repo.search_events_by_entities(
            entity_ids,
            tenant_id=tenant_id,
            limit=limit,
            document_ids=config.document_ids,
            dataset_id=config.dataset_id,
            account_id=config.account_id,
        )
    )


def _content_results(
    event_repo: EventRepository,
    *,
    config: SearchConfig,
    tenant_id: object,
    lexical_first_event_results: list[dict[str, Any]],
    vector_recall_enabled: bool,
    query_vec: list[float],
) -> list[dict[str, Any]]:
    content_results: list[dict[str, Any]] = list(lexical_first_event_results or [])
    if vector_recall_enabled and query_vec:
        try:
            content_results = event_repo.search_similar_by_content(
                query_vector=query_vec,
                tenant_id=tenant_id,
                k=config.recall.vector_candidates,
                document_ids=config.document_ids,
                dataset_id=config.dataset_id,
                account_id=config.account_id,
            )
        except Exception:
            content_results = []
    if content_results:
        return content_results
    try:
        return event_repo.search_events_lexical(
            query=str(config.query or ""),
            tenant_id=tenant_id,
            k=config.recall.vector_candidates,
            document_ids=config.document_ids,
            dataset_id=config.dataset_id,
            account_id=config.account_id,
        )
    except Exception:
        return []


def _select_query_events(
    content_results: list[dict[str, Any]],
    *,
    threshold: float,
    max_results: int,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    event_query_related = [item for item in content_results if item.get("similarity", 0.0) >= threshold][:max_results]
    direct_event_scores = {
        str(item.get("event_id")): float(item.get("similarity", 0.0) or 0.0)
        for item in event_query_related
        if item.get("event_id") is not None
    }
    return event_query_related, direct_event_scores


def _record_query_event_clues(
    tracker: Tracker,
    *,
    config: SearchConfig,
    event_query_related: list[dict[str, Any]],
) -> None:
    for event in event_query_related:
        tracker.add_clue(
            stage="recall",
            from_node=Tracker.build_query_node(config),
            to_node=Tracker.build_event_node({"id": event["event_id"], "title": event.get("title")}),
            confidence=event.get("similarity", 0.0),
            relation="query->event",
            metadata={"method": str(event.get("method") or "vector_search"), "step": "step3"},
        )


def _event_hops(
    *,
    event_ids_from_entities: list[Any],
    event_ids_from_relation_entities: list[Any],
    event_query_related: list[dict[str, Any]],
) -> dict[str, int]:
    event_hops: dict[str, int] = {}
    for event_id in event_ids_from_entities:
        key = str(event_id)
        event_hops[key] = min(int(event_hops.get(key, 99) or 99), 2)
    for event_id in event_ids_from_relation_entities:
        key = str(event_id)
        event_hops[key] = min(int(event_hops.get(key, 99) or 99), 3)
    for event in event_query_related:
        event_id = event.get("event_id")
        if event_id is None:
            continue
        key = str(event_id)
        event_hops[key] = min(int(event_hops.get(key, 99) or 99), 1)
    return event_hops


def _merged_event_ids(
    *,
    event_ids_from_entities: list[Any],
    event_ids_from_relation_entities: list[Any],
    event_query_related: list[dict[str, Any]],
    candidate_max_events: int,
) -> list[Any]:
    return list(
        dict.fromkeys(
            list(event_ids_from_entities)
            + list(event_ids_from_relation_entities)
            + [event["event_id"] for event in event_query_related]
        )
    )[:candidate_max_events]


def _event_scores(
    *,
    events_detail: list[Any],
    assoc_map: dict[str, list[Any]],
    query_vec: list[float],
    key_weights: dict[str, float],
    direct_event_scores: dict[str, float],
) -> dict[str, float]:
    event_scores: dict[str, float] = {}
    for event in events_detail:
        event_id = str(event.id)
        similarity = cosine_similarity(query_vec, event.content_vector) if event.content_vector else 0.0
        boost = 0.0
        for link in assoc_map.get(event_id, []):
            boost += key_weights.get(str(link.entity_id), 0.0)
        combined_score = similarity * 0.6 + boost * 0.4
        event_scores[event_id] = max(combined_score, float(direct_event_scores.get(event_id, 0.0) or 0.0))
    return event_scores


def _apply_serving_budget(
    events_detail: list[Any],
    *,
    event_scores: dict[str, float],
    event_hops: dict[str, int],
    limits: _RecallLimits,
    mode_overrides: dict[str, Any],
) -> tuple[list[str], dict[str, float], dict[str, int], ServingLayerBudgetResult]:
    merged_event_ids = [str(event.id) for event in events_detail]
    merged_event_ids.sort(key=lambda event_id: event_scores.get(str(event_id), 0.0), reverse=True)
    events_by_id = {str(event.id): event for event in events_detail}
    serving_result = apply_serving_layer_budget(
        [events_by_id[event_id] for event_id in merged_event_ids if event_id in events_by_id],
        event_scores,
        enabled=limits.serving_enabled,
        max_events_per_chunk=int(getattr(settings, "KG_SEARCH_SERVING_MAX_EVENTS_PER_CHUNK", 2) or 0),
        max_events_per_document=int(getattr(settings, "KG_SEARCH_SERVING_MAX_EVENTS_PER_DOCUMENT", 80) or 0),
        min_score=float(getattr(settings, "KG_SEARCH_SERVING_MIN_SCORE", 0.0) or 0.0),
        bypass=_should_bypass_serving_layer(
            mode=str(limits.mode_norm),
            reason_codes=[str(item) for item in (mode_overrides.get("reason_codes") or []) if str(item).strip()],
        ),
    )
    trimmed_event_ids = serving_result.event_ids[: limits.target_max_events]
    trimmed_scores = {event_id: float(event_scores.get(event_id, 0.0) or 0.0) for event_id in trimmed_event_ids}
    trimmed_hops = {event_id: int(event_hops.get(event_id, 1) or 1) for event_id in trimmed_event_ids}
    return trimmed_event_ids, trimmed_scores, trimmed_hops, serving_result


def _key_event_weights(
    merged_event_ids: list[str],
    *,
    event_scores: dict[str, float],
    assoc_map: dict[str, list[Any]],
) -> dict[str, float]:
    key_weights: dict[str, float] = {}
    for event_id in merged_event_ids:
        event_weight = event_scores.get(str(event_id), 0.0)
        for link in assoc_map.get(str(event_id), []):
            entity_id = str(link.entity_id)
            key_weights[entity_id] = key_weights.get(entity_id, 0.0) + event_weight
    return key_weights


def _merge_key_weights(key_weights: dict[str, float], key_event_weights: dict[str, float]) -> None:
    for entity_id, weight in key_event_weights.items():
        key_weights[entity_id] = key_weights.get(entity_id, 0.0) * 0.5 + weight * 0.5


def _final_keys(
    key_query_related: list[dict[str, Any]],
    *,
    key_weights: dict[str, float],
    entity_weight_threshold: float,
    final_entity_count: int,
) -> list[dict[str, Any]]:
    key_final = [
        {
            **entity,
            "weight": key_weights.get(entity["entity_id"], 0.0),
        }
        for entity in key_query_related
        if key_weights.get(entity["entity_id"], 0.0) >= entity_weight_threshold
    ]
    key_final.sort(key=lambda item: item.get("weight", 0.0), reverse=True)
    return key_final[:final_entity_count]


def _serving_layer_debug(
    *,
    limits: _RecallLimits,
    serving_result: ServingLayerBudgetResult,
    events_detail: list[Any],
    merged_event_ids: list[str],
) -> dict[str, Any]:
    return {
        "enabled": bool(limits.serving_enabled),
        "reason": str(serving_result.reason),
        "candidate_events": int(len(events_detail)),
        "kept": int(serving_result.kept),
        "returned": int(len(merged_event_ids)),
        "dropped": int(serving_result.dropped),
        "dropped_by_score": int(serving_result.dropped_by_score),
        "dropped_by_chunk": int(serving_result.dropped_by_chunk),
        "dropped_by_document": int(serving_result.dropped_by_document),
        "max_events": int(limits.target_max_events),
        "candidate_multiplier": int(limits.serving_candidate_multiplier),
    }


class RecallSearcher:
    def __init__(self):
        self.processor = DocumentProcessor()

    async def search(self, config: SearchConfig) -> RecallResult:
        tracker = Tracker()
        if config.document_ids is not None and not config.document_ids:
            return _empty_scope_result()

        session = get_session()
        try:
            entity_repo = EntityRepository(session)
            alias_repo = AliasRepository(session)
            event_repo = EventRepository(session)
            tenant_id = config.tenant_id or settings.DEFAULT_TENANT_ID
            limits = _build_recall_limits(config)
            alias_hits = _match_alias_hits(
                alias_repo,
                query=str(config.query or ""),
                tenant_id=tenant_id,
                max_entities=limits.max_entities,
            )
            expanded_query = _expand_query_with_alias_hits(str(config.query or ""), alias_hits)
            lexical_first_event_results = _lexical_first_event_results(
                event_repo,
                config=config,
                tenant_id=tenant_id,
                enabled=limits.prefer_lexical_first,
            )
            query_vec: list[float] = []
            raw_entities: list[dict[str, Any]] = []
            if limits.vector_recall_enabled and not (limits.prefer_lexical_first and lexical_first_event_results):
                query_vec = await _query_embedding(self.processor, expanded_query)
                raw_entities = _vector_entity_hits(
                    entity_repo,
                    query_vec=query_vec,
                    tenant_id=tenant_id,
                    vector_candidates=config.recall.vector_candidates,
                )
            alias_key_ids = _merge_alias_hits(
                tracker,
                config=config,
                raw_entities=raw_entities,
                alias_hits=alias_hits,
            )
            _lexical_entity_fallback(
                tracker,
                entity_repo,
                config=config,
                tenant_id=tenant_id,
                raw_entities=raw_entities,
                alias_hits=alias_hits,
                max_entities=limits.max_entities,
            )
            _apply_graph_embedding_recall(
                tracker,
                session,
                entity_repo,
                event_repo,
                config=config,
                tenant_id=tenant_id,
                alias_key_ids=alias_key_ids,
                vector_recall_enabled=limits.vector_recall_enabled,
                query_vec=query_vec,
                raw_entities=raw_entities,
            )
            raw_entities = _filter_skill_entities(
                raw_entities,
                include_skill_entities=bool(getattr(config, "include_skill_entities", True)),
            )
            raw_entities = _filter_entities_to_scope(
                event_repo,
                config=config,
                tenant_id=tenant_id,
                raw_entities=raw_entities,
            )
            key_query_related = _key_query_related(
                raw_entities,
                threshold=config.recall.entity_similarity_threshold,
                max_entities=limits.max_entities,
            )
            _record_query_entity_clues(
                tracker,
                config=config,
                key_query_related=key_query_related,
            )
            key_weights = _normalize_key_weights(key_query_related)
            relation_neighbor_ids, relation_debug = _apply_relation_expansion(
                tracker,
                session,
                config=config,
                tenant_id=tenant_id,
                mode_norm=limits.mode_norm,
                mode_overrides=limits.mode_overrides,
                key_query_related=key_query_related,
                key_weights=key_weights,
                alias_key_ids=alias_key_ids,
            )
            event_ids_from_entities = _search_events_by_entities(
                event_repo,
                config=config,
                tenant_id=tenant_id,
                entity_ids=[item["entity_id"] for item in key_query_related],
                limit=config.recall.vector_candidates * 2,
            )[: config.rerank.max_key_recall_results]
            event_ids_from_relation_entities: list[Any] = []
            if relation_neighbor_ids:
                event_ids_from_relation_entities = _search_events_by_entities(
                    event_repo,
                    config=config,
                    tenant_id=tenant_id,
                    entity_ids=relation_neighbor_ids,
                    limit=config.recall.vector_candidates * 2,
                )[: config.rerank.max_key_recall_results]
            content_results = _content_results(
                event_repo,
                config=config,
                tenant_id=tenant_id,
                lexical_first_event_results=lexical_first_event_results,
                vector_recall_enabled=limits.vector_recall_enabled,
                query_vec=query_vec,
            )
            event_query_related, direct_event_scores = _select_query_events(
                content_results,
                threshold=config.recall.event_similarity_threshold,
                max_results=config.rerank.max_query_recall_results,
            )
            _record_query_event_clues(
                tracker,
                config=config,
                event_query_related=event_query_related,
            )
            event_hops = _event_hops(
                event_ids_from_entities=event_ids_from_entities,
                event_ids_from_relation_entities=event_ids_from_relation_entities,
                event_query_related=event_query_related,
            )
            merged_event_ids = _merged_event_ids(
                event_ids_from_entities=event_ids_from_entities,
                event_ids_from_relation_entities=event_ids_from_relation_entities,
                event_query_related=event_query_related,
                candidate_max_events=limits.candidate_max_events,
            )
            events_detail = event_repo.get_events_by_ids(
                merged_event_ids,
                tenant_id=tenant_id,
                document_ids=config.document_ids,
                dataset_id=config.dataset_id,
                account_id=config.account_id,
            )
            merged_event_ids = [str(event.id) for event in events_detail]
            event_hops = {event_id: int(event_hops.get(event_id, 1) or 1) for event_id in merged_event_ids}
            assoc_map = event_repo.get_event_entities(merged_event_ids, tenant_id=tenant_id)
            event_scores = _event_scores(
                events_detail=events_detail,
                assoc_map=assoc_map,
                query_vec=query_vec,
                key_weights=key_weights,
                direct_event_scores=direct_event_scores,
            )
            merged_event_ids, event_scores, event_hops, serving_result = _apply_serving_budget(
                events_detail,
                event_scores=event_scores,
                event_hops=event_hops,
                limits=limits,
                mode_overrides=limits.mode_overrides,
            )
            _merge_key_weights(
                key_weights,
                _key_event_weights(
                    merged_event_ids,
                    event_scores=event_scores,
                    assoc_map=assoc_map,
                ),
            )
            return RecallResult(
                query_vector=query_vec,
                key_final=_final_keys(
                    key_query_related,
                    key_weights=key_weights,
                    entity_weight_threshold=limits.entity_weight_threshold,
                    final_entity_count=limits.final_entity_count,
                ),
                event_ids=merged_event_ids,
                clues=tracker.get_clues(),
                key_weights=key_weights,
                event_scores=event_scores,
                event_hops=event_hops,
                relation_debug=relation_debug,
                serving_layer=_serving_layer_debug(
                    limits=limits,
                    serving_result=serving_result,
                    events_detail=events_detail,
                    merged_event_ids=merged_event_ids,
                ),
            )
        finally:
            session.close()
