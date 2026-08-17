"""
Recall stage: 8-step pipeline (query -> keys -> events -> weights).
"""

from dataclasses import dataclass, field
from typing import Any

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


class RecallSearcher:
    def __init__(self):
        self.processor = DocumentProcessor()

    async def search(self, config: SearchConfig) -> RecallResult:
        tracker = Tracker()
        # Explicit empty doc scope must never broaden to tenant-wide KG search.
        # Treat `document_ids=[]` as "no accessible documents".
        if config.document_ids is not None and not config.document_ids:
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
        session = get_session()
        try:
            entity_repo = EntityRepository(session)
            alias_repo = AliasRepository(session)
            event_repo = EventRepository(session)
            tenant_id = config.tenant_id or settings.DEFAULT_TENANT_ID
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
            max_events = int(mode_overrides.get("max_events") or config.recall.max_events)
            mode_reason_codes = [str(x) for x in (mode_overrides.get("reason_codes") or []) if str(x).strip()]
            query_reason_codes = {
                str(x).strip() for x in (getattr(config, "query_mode_reason_codes", []) or []) if str(x).strip()
            }
            prefer_lexical_first = (config.dataset_id is not None or config.document_ids is not None) and (
                "low_confidence_global_budget" in set(mode_reason_codes)
                or (str(mode_norm) == "local" and bool({"dataset_factoid_scope", "quoted_term"} & query_reason_codes))
            )
            max_candidates = max(0, int(getattr(settings, "KG_SEARCH_MAX_RERANK_CANDIDATES", 0) or 0))
            if max_candidates > 0:
                max_events = min(max_events, max_candidates)
            target_max_events = max(1, int(max_events or 1))
            serving_enabled = bool(getattr(settings, "KG_SEARCH_SERVING_LAYER_ENABLED", True))
            serving_candidate_multiplier = max(
                1, int(getattr(settings, "KG_SEARCH_SERVING_CANDIDATE_MULTIPLIER", 3) or 3)
            )
            candidate_max_events = target_max_events
            if serving_enabled:
                candidate_max_events = target_max_events * serving_candidate_multiplier
                if max_candidates > 0:
                    candidate_max_events = min(candidate_max_events, max_candidates)
                candidate_max_events = max(target_max_events, candidate_max_events)
            max_entities = int(mode_overrides.get("max_entities") or config.recall.max_entities)
            final_entity_count = int(mode_overrides.get("final_entity_count") or config.recall.final_entity_count)
            entity_weight_threshold = float(
                mode_overrides.get("entity_weight_threshold") or config.recall.entity_weight_threshold
            )

            # === Step0: alias-aware query expansion (lexical) ===
            alias_key_ids: set[str] = set()
            expanded_query = str(config.query or "")
            try:
                alias_hits = alias_repo.match_aliases(
                    query=str(config.query or ""),
                    tenant_id=tenant_id,
                    limit=max(0, int(max_entities)),
                )
            except Exception:
                alias_hits = []

            if alias_hits:
                # Append canonical entity names to the query to help embedding recall.
                # Keep expansion bounded to avoid ballooning token count.
                names_added = 0
                expanded_fold = expanded_query.casefold()
                for hit in alias_hits[:5]:
                    nm = str((hit or {}).get("name") or "").strip()
                    if not nm:
                        continue
                    if nm.isascii() and nm.casefold() in expanded_fold:
                        continue
                    if not nm.isascii() and nm in expanded_query:
                        continue
                    expanded_query = f"{expanded_query} {nm}".strip()
                    names_added += 1
                    if names_added >= 5:
                        break

            # === Step1: query -> keys (vector) ===
            query_vec: list[float] = []
            raw_entities: list[dict] = []
            vector_recall_enabled = (
                bool(config.vector_recall_enabled)
                if getattr(config, "vector_recall_enabled", None) is not None
                else bool(getattr(settings, "KG_SEARCH_VECTOR_RECALL_ENABLED", True))
            )

            lexical_first_event_results: list[dict] = []
            if prefer_lexical_first:
                try:
                    lexical_first_event_results = event_repo.search_events_lexical(
                        query=str(config.query or ""),
                        tenant_id=tenant_id,
                        k=config.recall.vector_candidates,
                        document_ids=config.document_ids,
                        dataset_id=config.dataset_id,
                        account_id=config.account_id,
                    )
                except Exception:
                    lexical_first_event_results = []

            if vector_recall_enabled and not (prefer_lexical_first and lexical_first_event_results):
                try:
                    query_vec = await self.processor.generate_embedding(expanded_query)
                except Exception:
                    # CI/offline-friendly fallback: allow alias-driven recall to still function when
                    # embedding providers are unavailable or misconfigured.
                    query_vec = []

                if query_vec:
                    try:
                        raw_entities = entity_repo.search_similar(
                            query_vector=query_vec,
                            tenant_id=tenant_id,
                            k=config.recall.vector_candidates,
                        )
                    except Exception:
                        # Milvus may be unavailable in some environments (e.g. CI). Fall back to aliases.
                        raw_entities = []

            # Alias-aware keys: merge in alias hits as high-confidence candidates.
            if alias_hits:
                existing_ids = {str((e or {}).get("entity_id") or "").strip() for e in (raw_entities or [])}
                for hit in alias_hits:
                    eid = str((hit or {}).get("entity_id") or "").strip()
                    if not eid:
                        continue
                    alias_key_ids.add(eid)
                    if eid in existing_ids:
                        continue
                    raw_entities.append(hit)
                    existing_ids.add(eid)

                    tracker.add_clue(
                        stage="recall",
                        from_node=Tracker.build_query_node(config),
                        to_node=Tracker.build_entity_node(hit),
                        confidence=float((hit or {}).get("similarity", 1.0) or 1.0),
                        relation="query->entity:alias",
                        metadata={"method": "alias_match", "step": "step0"},
                    )

            if not raw_entities and not alias_hits:
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
                if lexical_entities:
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

            # === Optional Step1b: graph embeddings (node2vec-like) for entity recall ===
            #
            # This is designed for offline/CI scenarios where vector recall is disabled or unavailable.
            graph_enabled = (
                bool(config.graph_embeddings_enabled)
                if getattr(config, "graph_embeddings_enabled", None) is not None
                else bool(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_ENABLED", False))
            )
            if graph_enabled and alias_key_ids and (not vector_recall_enabled or not query_vec):
                try:
                    from uuid import UUID

                    # Params / caps (keep this bounded; it runs inline in recall).
                    max_graph_events = max(
                        0, int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_MAX_EVENTS", 200) or 200)
                    )
                    max_graph_entities = max(
                        0, int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_MAX_ENTITIES", 400) or 400)
                    )
                    max_graph_relations = max(
                        0, int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_MAX_RELATIONS", 1500) or 1500)
                    )
                    top_k = max(0, int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_TOP_K", 20) or 20))
                    min_sim = float(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_MIN_SIMILARITY", 0.35) or 0.35)
                    if top_k > 0 and max_graph_events > 0 and max_graph_entities > 0:
                        try:
                            tenant_uuid = UUID(str(tenant_id))
                        except Exception:
                            tenant_uuid = None

                        seed_entity_ids = sorted({str(eid) for eid in alias_key_ids if str(eid).strip()})
                        seed_nodes = [f"ent:{eid}" for eid in seed_entity_ids]
                        existing_ids = {str((e or {}).get("entity_id") or "").strip() for e in (raw_entities or [])}
                        seed_entity_map = {
                            str((e or {}).get("entity_id") or "").strip(): e
                            for e in (raw_entities or [])
                            if str((e or {}).get("entity_id") or "").strip()
                        }

                        # Build a local subgraph around seed entities via Event<->Entity links.
                        event_ids = event_repo.search_events_by_entities(
                            seed_entity_ids,
                            tenant_id=tenant_id,
                            limit=max_graph_events,
                            document_ids=config.document_ids,
                            dataset_id=config.dataset_id,
                            account_id=config.account_id,
                        )
                        event_id_strs = [str(eid) for eid in (event_ids or []) if eid is not None]
                        assoc_map = event_repo.get_event_entities(event_ids or [], tenant_id=tenant_uuid)

                        entity_counts: dict[str, int] = {}
                        for links in (assoc_map or {}).values():
                            for link in links or []:
                                ent_id = str(getattr(link, "entity_id", "") or "").strip()
                                if not ent_id:
                                    continue
                                entity_counts[ent_id] = int(entity_counts.get(ent_id, 0) or 0) + 1

                        # Keep seeds + top entities by co-occurrence frequency (bounded).
                        kept_entity_ids: set[str] = set(seed_entity_ids)
                        if max_graph_entities > 0 and len(kept_entity_ids) < max_graph_entities:
                            ranked = sorted(
                                [(eid, int(entity_counts.get(eid, 0) or 0)) for eid in entity_counts.keys()],
                                key=lambda x: (-int(x[1]), str(x[0])),
                            )
                            for eid, _cnt in ranked:
                                if len(kept_entity_ids) >= max_graph_entities:
                                    break
                                kept_entity_ids.add(str(eid))

                        # Optional: add relation edges among kept entities (only when relations enabled).
                        relation_edges: list[tuple[str, str]] = []
                        if (
                            tenant_uuid is not None
                            and max_graph_relations > 0
                            and bool(getattr(settings, "KG_RELATION_ENABLED", False))
                            and kept_entity_ids
                        ):
                            try:
                                # Reuse the relation expansion confidence gate to reduce drift.
                                min_conf = float(getattr(settings, "KG_SEARCH_RELATION_MIN_CONFIDENCE", 0.0) or 0.0)
                            except Exception:
                                min_conf = 0.0

                            ent_list = sorted(kept_entity_ids)
                            # Keep SQL parameter sizes bounded.
                            ent_list = ent_list[: min(len(ent_list), 300)]
                            try:
                                rel_rows = RelationRepository(session).list_relations_for_entities(
                                    ent_list,
                                    tenant_id=tenant_uuid,
                                    document_ids=config.document_ids,
                                    dataset_id=config.dataset_id,
                                    account_id=config.account_id,
                                    min_confidence=(min_conf if min_conf > 0 else None),
                                    limit=max_graph_relations,
                                )
                            except Exception:
                                rel_rows = []
                            # Deterministic ordering independent of updated_at.
                            rel_rows = sorted(
                                rel_rows or [],
                                key=lambda r: (
                                    str(getattr(r, "subject_entity_id", "") or ""),
                                    str(getattr(r, "predicate", "") or ""),
                                    str(getattr(r, "object_entity_id", "") or ""),
                                    str(getattr(r, "id", "") or ""),
                                ),
                            )
                            for rel in rel_rows:
                                a = str(getattr(rel, "subject_entity_id", "") or "").strip()
                                b = str(getattr(rel, "object_entity_id", "") or "").strip()
                                if not a or not b:
                                    continue
                                if a not in kept_entity_ids or b not in kept_entity_ids:
                                    continue
                                relation_edges.append((a, b))

                        adjacency = graph_embeddings_mod.build_entity_event_adjacency(
                            seed_entity_ids=seed_entity_ids,
                            event_ids=event_id_strs,
                            event_entity_links={str(k): list(v or []) for k, v in (assoc_map or {}).items()},
                            kept_entity_ids=kept_entity_ids,
                            relation_edges=relation_edges,
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
                            top_k=top_k,
                            min_similarity=min_sim,
                            entity_prefix="ent:",
                        )

                        candidate_entity_ids: list[str] = []
                        hit_seed_by_entity: dict[str, str] = {}
                        hit_sim_by_entity: dict[str, float] = {}
                        for h in hits or []:
                            node_key = str(h.get("node_key") or "")
                            seed_key = str(h.get("seed_node_key") or "")
                            if not node_key.startswith("ent:"):
                                continue
                            ent_id = node_key.split(":", 1)[1]
                            if not ent_id or ent_id in existing_ids:
                                continue
                            candidate_entity_ids.append(ent_id)
                            if seed_key.startswith("ent:"):
                                hit_seed_by_entity[ent_id] = seed_key.split(":", 1)[1]
                            try:
                                hit_sim_by_entity[ent_id] = float(h.get("similarity", 0.0) or 0.0)
                            except Exception:
                                hit_sim_by_entity[ent_id] = 0.0

                        if candidate_entity_ids:
                            ents = entity_repo.get_entities_by_ids(candidate_entity_ids, tenant_id=tenant_uuid)
                            ent_by_id = {str(getattr(e, "id", "") or ""): e for e in (ents or [])}
                            for ent_id in candidate_entity_ids:
                                if ent_id in existing_ids:
                                    continue
                                obj = ent_by_id.get(str(ent_id))
                                if obj is None:
                                    continue

                                sim = float(hit_sim_by_entity.get(ent_id, 0.0) or 0.0)
                                ent_dict = {
                                    "entity_id": str(ent_id),
                                    "name": str(getattr(obj, "name", "") or ""),
                                    "type": str(getattr(obj, "type", "") or "unknown"),
                                    "similarity": sim,
                                    "tenant_id": str(tenant_id),
                                    "method": "graph_embedding",
                                }
                                raw_entities.append(ent_dict)
                                existing_ids.add(str(ent_id))

                                seed_id = str(hit_seed_by_entity.get(ent_id, "") or "").strip()
                                if seed_id:
                                    tracker.add_clue(
                                        stage="recall",
                                        from_node=Tracker.build_entity_node(
                                            seed_entity_map.get(seed_id)
                                            or {"entity_id": seed_id, "name": "", "type": "unknown"}
                                        ),
                                        to_node=Tracker.build_entity_node(ent_dict),
                                        confidence=sim,
                                        relation="entity->entity:graph_embedding",
                                        metadata={"method": "graph_embedding", "step": "step1b"},
                                    )
                except Exception as exc:
                    # Best-effort: graph recall must never crash KG search.
                    logger.debug("Graph embedding recall failed; continuing KG search without it: %s", exc)
            if not bool(getattr(config, "include_skill_entities", True)):
                raw_entities = [
                    e
                    for e in (raw_entities or [])
                    if str((e or {}).get("type") or "").strip() not in {"Skill", "SkillTag", "SkillCategory"}
                ]
            if raw_entities and (config.document_ids is not None or config.dataset_id is not None):
                # Prevent cross-document leakage within tenant: only keep entities that appear
                # in events scoped by the requested documents or dataset.
                from uuid import UUID

                candidate_ids = [e.get("entity_id") or e.get("id") for e in raw_entities]
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

                if allowed_entity_ids is not None:
                    filtered_entities: list[dict] = []
                    for ent in raw_entities:
                        ent_id = ent.get("entity_id") or ent.get("id")
                        if ent_id is None:
                            continue
                        try:
                            ent_uuid = UUID(str(ent_id))
                        except Exception:
                            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                            continue
                        if ent_uuid in allowed_entity_ids:
                            filtered_entities.append(ent)
                    raw_entities = filtered_entities
            key_query_related = [
                e for e in raw_entities if e.get("similarity", 0.0) >= config.recall.entity_similarity_threshold
            ][:max_entities]

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
            key_weights: dict[str, float] = {}
            if key_query_related:
                sims = [e.get("similarity", 0.0) for e in key_query_related]
                mx = max(sims) or 1.0
                for ent in key_query_related:
                    key_weights[ent["entity_id"]] = ent.get("similarity", 0.0) / mx

            # === Optional Step1.5: keys -> neighbor entities (relations) ===
            relation_neighbor_ids: list[str] = []
            relation_debug: dict[str, Any] = {
                "enabled": False,
                "query_mode": str(mode_norm),
                "query_mode_reason_codes": [
                    str(x) for x in (mode_overrides.get("reason_codes") or []) if str(x).strip()
                ][:8],
            }
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
                    weight_factor = float(getattr(settings, "KG_SEARCH_RELATION_NEIGHBOR_WEIGHT_FACTOR", 0.7) or 0.7)
                    bucket_low = float(getattr(settings, "KG_SEARCH_RELATION_CONF_BUCKET_LOW_MAX", 0.4) or 0.4)
                    bucket_mid = float(getattr(settings, "KG_SEARCH_RELATION_CONF_BUCKET_MID_MAX", 0.7) or 0.7)

                    try:
                        from uuid import UUID

                        tenant_uuid = UUID(str(tenant_id))
                    except Exception:
                        tenant_uuid = None

                    if tenant_uuid is not None:
                        relation_debug = {
                            "enabled": True,
                            "query_mode": str(mode_norm),
                            "query_mode_reason_codes": [
                                str(x) for x in (mode_overrides.get("reason_codes") or []) if str(x).strip()
                            ][:8],
                            "min_confidence": float(min_confidence),
                            "max_edges": int(max_edges),
                            "max_neighbors": int(max_neighbors),
                            "weight_factor": float(weight_factor),
                            "conf_bucket_low_max": float(bucket_low),
                            "conf_bucket_mid_max": float(bucket_mid),
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
                        neighbor_weights: dict[str, float] = {}
                        predicate_hist: dict[str, int] = {}
                        conf_bucket_hist: dict[str, int] = {"low": 0, "mid": 0, "high": 0}
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

                            # Safety rail (Wave15): when a key was introduced via alias match, only
                            # expand through evidence-anchored edges (reduce drift from ambiguous aliases).
                            if from_id in alias_key_ids:
                                refs = getattr(rel, "references", None)
                                evidence_quote = (
                                    str(refs.get("evidence_quote") or "").strip() if isinstance(refs, dict) else ""
                                )
                                if not evidence_quote:
                                    continue

                            pred_mult = relation_multiplier(predicate, from_is_subject=bool(from_id == subj))
                            if pred_mult <= 0:
                                continue
                            evidence_mult = 1.0
                            evidence_source = ""
                            try:
                                refs = getattr(rel, "references", None)
                                evidence_source = (
                                    str(refs.get("evidence_source") or "").strip().casefold()
                                    if isinstance(refs, dict)
                                    else ""
                                )
                                if evidence_source == "mention":
                                    mention_mult = float(
                                        getattr(settings, "KG_SEARCH_RELATION_MENTION_EVIDENCE_MULTIPLIER", 0.7) or 0.7
                                    )
                                    evidence_mult = max(0.0, min(1.0, float(mention_mult)))
                            except Exception:
                                evidence_mult = 1.0
                                evidence_source = ""

                            w = (
                                float(key_weights.get(from_id, 0.0) or 0.0)
                                * conf
                                * float(weight_factor)
                                * pred_mult
                                * float(evidence_mult)
                            )
                            if w <= 0:
                                continue

                            bucket = confidence_bucket(conf, low_max=bucket_low, mid_max=bucket_mid)
                            neighbor_weights[to_id] = max(neighbor_weights.get(to_id, 0.0), w)
                            predicate_hist[predicate] = int(predicate_hist.get(predicate, 0) or 0) + 1
                            conf_bucket_hist[bucket] = int(conf_bucket_hist.get(bucket, 0) or 0) + 1
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
                                    "evidence_multiplier": float(evidence_mult),
                                    "evidence_source": evidence_source,
                                    "confidence_bucket": bucket,
                                    # Provenance (best-effort): allow diagnostics/UI to trace edges back to source.
                                    "relation_id": str(getattr(rel, "id", "") or "") or None,
                                    "relation_document_id": (str(getattr(rel, "document_id", "") or "") or None),
                                    "relation_chunk_id": str(getattr(rel, "chunk_id", "") or "") or None,
                                    "relation_event_id": str(getattr(rel, "event_id", "") or "") or None,
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
                        relation_debug["predicate_hist"] = dict(
                            sorted(predicate_hist.items(), key=lambda x: (-x[1], x[0]))
                        )  # type: ignore[assignment]
                        relation_debug["confidence_bucket_hist"] = dict(conf_bucket_hist)

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

            event_ids_from_relation_entities: list[str] = []
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
            content_results: list[dict] = list(lexical_first_event_results or [])
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
            if not content_results:
                # Vector recall can legitimately miss compositional user queries
                # (for example "QUIC transport handshake") even when scoped KG
                # rows contain matching terms. Keep the fallback scope-aware so
                # a weak vector hit never broadens dataset/document access.
                try:
                    content_results = event_repo.search_events_lexical(
                        query=str(config.query or ""),
                        tenant_id=tenant_id,
                        k=config.recall.vector_candidates,
                        document_ids=config.document_ids,
                        dataset_id=config.dataset_id,
                        account_id=config.account_id,
                    )
                except Exception:
                    content_results = []
            event_query_related = [
                item
                for item in content_results
                if item.get("similarity", 0.0) >= config.recall.event_similarity_threshold
            ]
            event_query_related = event_query_related[: config.rerank.max_query_recall_results]
            direct_event_scores = {
                str(item.get("event_id")): float(item.get("similarity", 0.0) or 0.0)
                for item in event_query_related
                if item.get("event_id") is not None
            }

            for ev in event_query_related:
                tracker.add_clue(
                    stage="recall",
                    from_node=Tracker.build_query_node(config),
                    to_node=Tracker.build_event_node({"id": ev["event_id"], "title": ev.get("title")}),
                    confidence=ev.get("similarity", 0.0),
                    relation="query->event",
                    metadata={"method": str(ev.get("method") or "vector_search"), "step": "step3"},
                )

            # === Step4: merge events ===
            event_hops: dict[str, int] = {}
            for eid in event_ids_from_entities:
                key = str(eid)
                prev = event_hops.get(key)
                event_hops[key] = min(int(prev or 99), 2)
            for eid in event_ids_from_relation_entities:
                key = str(eid)
                prev = event_hops.get(key)
                event_hops[key] = min(int(prev or 99), 3)
            for ev in event_query_related:
                eid = ev.get("event_id")
                if eid is None:
                    continue
                key = str(eid)
                prev = event_hops.get(key)
                event_hops[key] = min(int(prev or 99), 1)

            merged_event_ids = list(
                dict.fromkeys(
                    list(event_ids_from_entities)
                    + list(event_ids_from_relation_entities)
                    + [e["event_id"] for e in event_query_related]
                )
            )[:candidate_max_events]

            # === Step5/6: compute event-key weights & event scores ===
            events_detail = event_repo.get_events_by_ids(
                merged_event_ids,
                tenant_id=tenant_id,
                document_ids=config.document_ids,
                dataset_id=config.dataset_id,
                account_id=config.account_id,
            )
            merged_event_ids = [str(ev.id) for ev in events_detail]
            # Drop hop entries for filtered-out events (ACL / scope trimming).
            event_hops = {eid: int(event_hops.get(eid, 1) or 1) for eid in merged_event_ids}
            assoc_map = event_repo.get_event_entities(merged_event_ids, tenant_id=tenant_id)

            event_scores: dict[str, float] = {}
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
                combined_score = sim * 0.6 + boost * 0.4
                # Direct query->event recall is often the highest-precision signal
                # for dataset-scoped factoid KG search. Preserve it instead of
                # recomputing to zero when vector recall is intentionally skipped.
                event_scores[ev_id] = max(combined_score, float(direct_event_scores.get(ev_id, 0.0) or 0.0))

            # sort events by score and trim
            merged_event_ids.sort(key=lambda eid: event_scores.get(str(eid), 0.0), reverse=True)
            events_by_id = {str(ev.id): ev for ev in events_detail}
            serving_result = apply_serving_layer_budget(
                [events_by_id[eid] for eid in merged_event_ids if eid in events_by_id],
                event_scores,
                enabled=serving_enabled,
                max_events_per_chunk=int(getattr(settings, "KG_SEARCH_SERVING_MAX_EVENTS_PER_CHUNK", 2) or 0),
                max_events_per_document=int(getattr(settings, "KG_SEARCH_SERVING_MAX_EVENTS_PER_DOCUMENT", 80) or 0),
                min_score=float(getattr(settings, "KG_SEARCH_SERVING_MIN_SCORE", 0.0) or 0.0),
                bypass=_should_bypass_serving_layer(
                    mode=str(mode_norm),
                    reason_codes=[str(x) for x in (mode_overrides.get("reason_codes") or []) if str(x).strip()],
                ),
            )
            merged_event_ids = serving_result.event_ids[:target_max_events]
            event_scores = {eid: float(event_scores.get(eid, 0.0) or 0.0) for eid in merged_event_ids}
            event_hops = {eid: int(event_hops.get(eid, 1) or 1) for eid in merged_event_ids}

            # === Step7: backprop key weights from events ===
            key_event_weights: dict[str, float] = {}
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
                if key_weights.get(e["entity_id"], 0.0) >= entity_weight_threshold
            ]
            key_final.sort(key=lambda x: x.get("weight", 0.0), reverse=True)
            key_final = key_final[:final_entity_count]

            return RecallResult(
                query_vector=query_vec,
                key_final=key_final,
                event_ids=merged_event_ids,
                clues=tracker.get_clues(),
                key_weights=key_weights,
                event_scores=event_scores,
                event_hops=event_hops,
                relation_debug=relation_debug,
                serving_layer={
                    "enabled": bool(serving_enabled),
                    "reason": str(serving_result.reason),
                    "candidate_events": int(len(events_detail)),
                    "kept": int(serving_result.kept),
                    "returned": int(len(merged_event_ids)),
                    "dropped": int(serving_result.dropped),
                    "dropped_by_score": int(serving_result.dropped_by_score),
                    "dropped_by_chunk": int(serving_result.dropped_by_chunk),
                    "dropped_by_document": int(serving_result.dropped_by_document),
                    "max_events": int(target_max_events),
                    "candidate_multiplier": int(serving_candidate_multiplier),
                },
            )
        finally:
            session.close()
