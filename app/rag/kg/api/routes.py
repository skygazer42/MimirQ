import asyncio
import contextlib
import gzip
import time
import uuid
from datetime import UTC
from typing import Annotated, Any
from uuid import UUID

# GraphML export only constructs and serializes a new tree; no untrusted XML is parsed.
from xml.etree import ElementTree as ET  # nosemgrep: python.lang.security.use-defused-xml.use-defused-xml

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.config import settings
from app.core.database import get_db
from app.rag.core.logging import get_logger

# Names split into app.rag.kg.api.routes_support are re-imported below so that
# every pre-split reference (``app.rag.kg.api.routes.<name>``) keeps working.
# The F401 suppressions mark names that are only re-exported, not used in this module.
from app.rag.kg.api.routes_support.common import (
    KG_API_FALLBACK_LOG_MESSAGE,
    KG_ENTITY_NOT_FOUND_DETAIL,
    KG_EXTRACTION_ALREADY_QUEUED_DETAIL,  # noqa: F401
    KG_PIPELINE_CHUNKS_NOT_FOUND_DETAIL,  # noqa: F401
)
from app.rag.kg.api.routes_support.extraction import (
    _audit_kg_extraction,
    _default_prompt_template_id,  # noqa: F401
    _document_chunks_for_extraction,
    _document_kg_python_plugin,  # noqa: F401
    _effective_kg_extraction_options,
    _enqueue_kg_extraction_response,
    _extraction_audit_details,
    _get_extraction_document,
    _run_sync_kg_extraction,
    _scope_chunks_to_pipeline,
    _selected_extraction_pipeline_hash,  # noqa: F401
)
from app.rag.kg.api.routes_support.merge_alias import (
    _add_resolution_audit_log,
    _alias_suggestion_item,  # noqa: F401
    _apply_merge_relation_updates,
    _commit_or_rollback,
    _create_merge_action,
    _dedupe_merged_event_entity_edges,
    _delete_duplicate_target_assocs,  # noqa: F401
    _delete_source_entity_vector_if_enabled,
    _ensure_merge_redirect,
    _entity_relation_rows,
    _merge_affected_rows,
    _merge_duplicate_assoc_fields,  # noqa: F401
    _merge_targets,
    _offline_alias_suggestions,
    _score_alias_candidates,  # noqa: F401
    _target_assoc_to_keep,  # noqa: F401
    _vector_alias_suggestion_item,  # noqa: F401
    _vector_alias_suggestions,
)
from app.rag.kg.api.routes_support.projection import (
    _active_pipeline_hash_expr,  # noqa: F401
    _add_kg_entity_cooccurrence_links,  # noqa: F401
    _append_relation_links,  # noqa: F401
    _apply_event_pipeline_scope,
    _apply_relation_pipeline_scope,  # noqa: F401
    _audit_hash_text,
    _build_kg_graph_response_from_events,
    _chunk_matches_pipeline,  # noqa: F401
    _dict_list,  # noqa: F401
    _doc_pipeline_hash,  # noqa: F401
    _empty_kg_graph_response,
    _ensure_enabled,
    _event_entity_nodes_and_links,  # noqa: F401
    _event_entity_snapshot,  # noqa: F401
    _event_ids_for_center_entity,  # noqa: F401
    _expanded_kg_events_for_node,
    _kg_allowed_entities,  # noqa: F401
    _kg_entity_cooccurrence_counts,  # noqa: F401
    _kg_entity_node,  # noqa: F401
    _kg_event_degrees,  # noqa: F401
    _kg_event_entity_link,  # noqa: F401
    _kg_event_entity_rows,  # noqa: F401
    _kg_event_node,  # noqa: F401
    _kg_graph_limits,
    _kg_limit_value,  # noqa: F401
    _kg_relation_link,  # noqa: F401
    _load_events_by_ids,  # noqa: F401
    _load_kg_projection_events,
    _log_kg_api_metric,
    _log_kg_graph_metric,
    _related_event_ids_for_center_event,  # noqa: F401
    _relation_snapshot,  # noqa: F401
    _resolve_allowed_documents,
    _resolve_entity_id_via_redirects,
    _stable_group_for,
    _uuid_list,  # noqa: F401
    _uuid_or_none,  # noqa: F401
)
from app.rag.kg.api.routes_support.schemas import (
    KGExtractionEffectiveOptions,  # noqa: F401
    KGExtractionOptions,
    KGGraphBuildResult,  # noqa: F401
    KGGraphExportFlags,
    KGGraphProjectionLimits,  # noqa: F401
    KGGraphProjectionParams,
    KGMergeAffectedRows,  # noqa: F401
    KGMergeSideEffects,  # noqa: F401
    KGMergeTargets,  # noqa: F401
    KGSnapshotCounts,
    KGSnapshotDetailRows,
    KGUndoStats,  # noqa: F401
)
from app.rag.kg.api.routes_support.undo import (
    _delete_orphan_split_entity,  # noqa: F401
    _dict_or_none,  # noqa: F401
    _get_applied_resolution_action,
    _limited_optional_str,  # noqa: F401
    _remove_merge_redirect,  # noqa: F401
    _resolution_action_kind,
    _restore_deleted_assoc_rows,  # noqa: F401
    _restore_deleted_relation_rows,  # noqa: F401
    _restore_source_entity_vector_if_needed,  # noqa: F401
    _restore_split_relations,  # noqa: F401
    _restore_updated_assocs,  # noqa: F401
    _restore_updated_relations,  # noqa: F401
    _restored_relation_row_payload,  # noqa: F401
    _undo_merge_resolution_action,
    _undo_split_resolution_action,
)
from app.rag.kg.pipeline import kg_search
from app.rag.kg.schemas import (
    KGDeleteResponse,
    KGEntityAliasCreateRequest,
    KGEntityAliasesResponse,
    KGEntityAliasItem,
    KGEntityAliasSuggestionItem,  # noqa: F401
    KGEntityAliasSuggestionsResponse,
    KGEntityDetailResponse,
    KGEntityItem,
    KGEntityMergePreviewResponse,
    KGEntityMergeRequest,
    KGEntityMergeResponse,
    KGEntityResolutionUndoResponse,
    KGEntitySplitRequest,
    KGEntitySplitResponse,
    KGEventDetailResponse,
    KGEventEntityItem,
    KGEventItem,
    KGExtractResponse,
    KGGraphNode,
    KGGraphResponse,
    KGManualImportDeleteResponse,
    KGManualImportListResponse,
    KGManualImportPreviewResponse,
    KGManualImportRequest,
    KGManualImportResponse,
    KGPredicateOntologyCreateRequest,
    KGPredicateOntologyItem,
    KGPredicateOntologyListResponse,
    KGPredicateOntologyUpdateRequest,
    KGSearchRequest,
    KGSearchResponse,
    KGStatsResponse,
)
from app.services.dataset_service import DatasetService
from app.services.document_access import filter_allowed_document_ids

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger(__name__)

PIPELINE_VERSION_FILTER_DESC = "Optional pipeline version filter (defaults to active pipeline per document)"
DATASET_SCOPE_FILTER_DESC = "Optional dataset scope resolved server-side to accessible documents"
INCLUDE_ENTITY_LINKS_DESC = "Include entity-entity co-occurrence links"
INCLUDE_RELATION_LINKS_DESC = "Include entity-entity relation links (triples)"
KG_API_GRAPH_METRIC = "kg.api.graph"
KG_API_GRAPH_EXPAND_METRIC = "kg.api.graph_expand"


def kg_graph_projection_params(
    document_ids: Annotated[list[UUID] | None, Query()] = None,
    dataset_id: Annotated[UUID | None, Query(description=DATASET_SCOPE_FILTER_DESC)] = None,
    pipeline_hash: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=200,
            description=PIPELINE_VERSION_FILTER_DESC,
        ),
    ] = None,
    max_events: Annotated[int | None, Query(ge=1, le=2000)] = None,
    max_entities: Annotated[int | None, Query(ge=1, le=5000)] = None,
    max_links: Annotated[int | None, Query(ge=1, le=20000)] = None,
    include_entity_links: Annotated[bool, Query(description=INCLUDE_ENTITY_LINKS_DESC)] = False,
    include_relation_links: Annotated[bool, Query(description=INCLUDE_RELATION_LINKS_DESC)] = False,
    min_shared_events: Annotated[int | None, Query(ge=1, le=100)] = None,
    max_entity_links: Annotated[int | None, Query(ge=0, le=20000)] = None,
) -> KGGraphProjectionParams:
    return KGGraphProjectionParams(
        document_ids=document_ids,
        dataset_id=dataset_id,
        pipeline_hash=pipeline_hash,
        max_events=max_events,
        max_entities=max_entities,
        max_links=max_links,
        include_entity_links=include_entity_links,
        include_relation_links=include_relation_links,
        min_shared_events=min_shared_events,
        max_entity_links=max_entity_links,
    )


def kg_graph_export_flags(
    download: Annotated[bool, Query()] = True,
    gzip_output: Annotated[bool, Query(alias="gzip", description="Return gzipped GraphML")] = False,
) -> KGGraphExportFlags:
    return KGGraphExportFlags(
        download=download,
        gzip_output=gzip_output,
    )


def kg_extraction_options(
    async_mode: Annotated[bool, Query(alias="async")] = False,
    pipeline_hash: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=200,
            description="Optional pipeline hash override (defaults to active pipeline)",
        ),
    ] = None,
    replace_existing: Annotated[
        bool | None, Query(description="Replace previously extracted events for this document")
    ] = None,
    prune_orphan_entities: Annotated[
        bool | None, Query(description="Prune entities with no remaining event links")
    ] = None,
    extract_relations: Annotated[
        bool | None, Query(description="Extract entity relations (triples) (override settings)")
    ] = None,
    extract_skills: Annotated[bool | None, Query(description="Extract Skill/SOP entities (override settings)")] = None,
    extraction_backend: Annotated[
        str | None, Query(description="Extraction backend override: llm, gliner, hybrid, heuristic")
    ] = None,
    prompt_template_id: Annotated[UUID | None, Query()] = None,
    prompt_template_key: Annotated[str | None, Query()] = None,
    prompt_ab_experiment_key: Annotated[str | None, Query()] = None,
) -> KGExtractionOptions:
    return KGExtractionOptions(
        async_mode=async_mode,
        pipeline_hash=pipeline_hash,
        replace_existing=replace_existing,
        prune_orphan_entities=prune_orphan_entities,
        extract_relations=extract_relations,
        extract_skills=extract_skills,
        extraction_backend=extraction_backend,
        prompt_template_id=prompt_template_id,
        prompt_template_key=prompt_template_key,
        prompt_ab_experiment_key=prompt_ab_experiment_key,
    )


@router.get("/graph", response_model=KGGraphResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_kg_graph(
    params: Annotated[KGGraphProjectionParams, Depends(kg_graph_projection_params)],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Return a graph-friendly projection of KG tables for visualization.

    Notes:
    - Requires KG_ENABLED=true.
    - If document_ids is not provided, it falls back to the current account's accessible documents.
    - The response is intentionally lightweight and capped by max_* params.
    """
    t0 = time.perf_counter()
    _ensure_enabled()

    allowed_doc_ids = _resolve_allowed_documents(
        document_ids=params.document_ids,
        dataset_id=params.dataset_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    if not allowed_doc_ids:
        return _empty_kg_graph_response(
            metric=KG_API_GRAPH_METRIC,
            t0=t0,
            tenant_id=tenant_id,
            docs=0,
            stats={"reason": "no_accessible_documents"},
        )

    from app.rag.kg.models import KgSourceEvent

    limits = _kg_graph_limits(params)
    events = _load_kg_projection_events(
        db,
        KgSourceEvent,
        tenant_id=tenant_id,
        allowed_doc_ids=allowed_doc_ids,
        pipeline_hash=params.pipeline_hash,
        max_events=limits.max_events,
    )

    if not events:
        return _empty_kg_graph_response(
            metric=KG_API_GRAPH_METRIC,
            t0=t0,
            tenant_id=tenant_id,
            docs=len(allowed_doc_ids),
            stats={"events": 0, "entities": 0, "links": 0},
        )

    result = _build_kg_graph_response_from_events(
        db,
        tenant_id=tenant_id,
        allowed_doc_ids=allowed_doc_ids,
        events=events,
        limits=limits,
        pipeline_hash=params.pipeline_hash,
    )
    out = result.response
    _log_kg_graph_metric(
        KG_API_GRAPH_METRIC,
        t0=t0,
        tenant_id=tenant_id,
        docs=len(allowed_doc_ids),
        events=int(out.stats.get("events", 0) or 0),
        entities=int(out.stats.get("entities", 0) or 0),
        links=int(out.stats.get("links", 0) or 0),
    )
    return out


@router.get("/graph/expand", response_model=KGGraphResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def expand_kg_graph(
    node_id: Annotated[UUID, Query(description="Center node id (KgSourceEvent.id or KgEntity.id)")],
    params: Annotated[KGGraphProjectionParams, Depends(kg_graph_projection_params)],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Expand a single node (event/entity) into a small neighborhood subgraph.

    - Requires KG_ENABLED=true.
    - Enforces document-level access control.
    """
    t0 = time.perf_counter()
    _ensure_enabled()

    allowed_doc_ids = _resolve_allowed_documents(
        document_ids=params.document_ids,
        dataset_id=params.dataset_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    if not allowed_doc_ids:
        return _empty_kg_graph_response(
            metric=KG_API_GRAPH_EXPAND_METRIC,
            t0=t0,
            tenant_id=tenant_id,
            docs=0,
            stats={"reason": "no_accessible_documents"},
        )

    limits = _kg_graph_limits(params, expand=True)
    events, empty_reason = _expanded_kg_events_for_node(
        db,
        tenant_id=tenant_id,
        node_id=node_id,
        allowed_doc_ids=allowed_doc_ids,
        pipeline_hash=params.pipeline_hash,
        max_events=limits.max_events,
    )
    if empty_reason:
        return _empty_kg_graph_response(
            metric=KG_API_GRAPH_EXPAND_METRIC,
            t0=t0,
            tenant_id=tenant_id,
            docs=len(allowed_doc_ids),
            stats={"reason": empty_reason},
        )

    if not events:
        return _empty_kg_graph_response(
            metric=KG_API_GRAPH_EXPAND_METRIC,
            t0=t0,
            tenant_id=tenant_id,
            docs=len(allowed_doc_ids),
            stats={"events": 0, "entities": 0, "links": 0},
        )

    result = _build_kg_graph_response_from_events(
        db,
        tenant_id=tenant_id,
        allowed_doc_ids=allowed_doc_ids,
        events=events,
        limits=limits,
        pipeline_hash=params.pipeline_hash,
        center_id=node_id,
    )
    out = result.response
    _log_kg_graph_metric(
        KG_API_GRAPH_EXPAND_METRIC,
        t0=t0,
        tenant_id=tenant_id,
        docs=len(allowed_doc_ids),
        events=int(out.stats.get("events", 0) or 0),
        entities=int(out.stats.get("entities", 0) or 0),
        links=int(out.stats.get("links", 0) or 0),
    )
    return out


def _kg_search_pattern(q_text: str) -> str:
    import re

    terms = [term for term in re.split(r"\s+", q_text) if term]
    return "%" + "%".join(terms[:6]) + "%" if terms else f"%{q_text}%"


def _kg_search_mode(kind: str) -> str:
    mode = (kind or "all").strip().lower()
    return mode if mode in {"all", "entity", "event"} else "all"


def _search_kg_entity_nodes(
    db: Session,
    *,
    tenant_id: UUID,
    allowed_doc_ids: list[UUID],
    pattern: str,
    pipeline_hash: str | None,
    limit: int,
) -> list[KGGraphNode]:
    from sqlalchemy import func, or_

    from app.rag.kg.models import KgEntity, KgEventEntity, KgSourceEvent

    ent_q = (
        db.query(KgEntity.id, func.max(KgEntity.updated_at).label("last_seen"))
        .join(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(
            KgEntity.tenant_id == tenant_id,
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
            or_(KgEntity.name.ilike(pattern), KgEntity.normalized_name.ilike(pattern)),
        )
    )
    ent_q = _apply_event_pipeline_scope(ent_q, pipeline_hash=pipeline_hash)
    ent_rows = ent_q.group_by(KgEntity.id).order_by(func.max(KgEntity.updated_at).desc()).limit(int(limit)).all()
    entity_ids = [row[0] for row in ent_rows if row and row[0]]
    if not entity_ids:
        return []

    ents_by_id = {
        ent.id: ent
        for ent in db.query(KgEntity).filter(KgEntity.tenant_id == tenant_id, KgEntity.id.in_(entity_ids)).all()
    }
    nodes: list[KGGraphNode] = []
    for entity_id in entity_ids:
        ent = ents_by_id.get(entity_id)
        if ent is not None:
            nodes.append(_kg_entity_search_node(ent))
    return nodes


def _kg_entity_search_node(ent: Any) -> KGGraphNode:
    return KGGraphNode(
        id=str(ent.id),
        label=(ent.name or "").strip() or str(ent.id),
        group=_stable_group_for(getattr(ent, "type", "") or "unknown"),
        val=1,
        meta={
            "kind": "entity",
            "type": getattr(ent, "type", None),
            "normalized_name": getattr(ent, "normalized_name", None),
        },
    )


def _kg_event_search_node(event: Any) -> KGGraphNode:
    return KGGraphNode(
        id=str(event.id),
        label=(event.title or "").strip() or str(event.id),
        group=0,
        val=1,
        meta={
            "kind": "event",
            "document_id": str(event.document_id) if event.document_id else "",
            "chunk_id": str(event.chunk_id) if event.chunk_id else "",
        },
    )


def _search_kg_event_nodes(
    db: Session,
    *,
    tenant_id: UUID,
    allowed_doc_ids: list[UUID],
    pattern: str,
    pipeline_hash: str | None,
    limit: int,
) -> list[KGGraphNode]:
    from sqlalchemy import or_

    from app.rag.kg.models import KgSourceEvent

    events_q = db.query(KgSourceEvent).filter(
        KgSourceEvent.tenant_id == tenant_id,
        KgSourceEvent.document_id.in_(allowed_doc_ids),
        or_(KgSourceEvent.title.ilike(pattern), KgSourceEvent.summary.ilike(pattern)),
    )
    events_q = _apply_event_pipeline_scope(events_q, pipeline_hash=pipeline_hash)
    return [
        _kg_event_search_node(event) for event in events_q.order_by(KgSourceEvent.updated_at.desc()).limit(limit).all()
    ]


@router.get("/graph/search", response_model=list[KGGraphNode], responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def search_kg_graph_nodes(
    q: Annotated[str, Query(min_length=1, max_length=200, description="Search query")],
    kind: Annotated[str, Query(description="entity | event | all")] = "all",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    document_ids: Annotated[list[UUID] | None, Query()] = None,
    dataset_id: Annotated[UUID | None, Query(description=DATASET_SCOPE_FILTER_DESC)] = None,
    pipeline_hash: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=200,
            description=PIPELINE_VERSION_FILTER_DESC,
        ),
    ] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Search KG nodes (entities/events) for UI autocomplete / quick jump.
    """
    _ensure_enabled()

    q_text = (q or "").strip()
    if not q_text:
        return []

    allowed_doc_ids = _resolve_allowed_documents(
        document_ids=document_ids,
        dataset_id=dataset_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    if not allowed_doc_ids:
        return []

    mode = _kg_search_mode(kind)
    pattern = _kg_search_pattern(q_text)
    nodes: list[KGGraphNode] = []

    if mode in {"all", "entity"}:
        # Entity search helper intentionally dedupes by group_by(KgEntity.id)
        # and orders by func.max(KgEntity.updated_at), not DISTINCT JSON rows.
        nodes.extend(
            _search_kg_entity_nodes(
                db,
                tenant_id=tenant_id,
                allowed_doc_ids=allowed_doc_ids,
                pattern=pattern,
                pipeline_hash=pipeline_hash,
                limit=int(limit),
            )
        )

    remaining = int(limit) - len(nodes)
    if remaining <= 0:
        return nodes[: int(limit)]

    if mode in {"all", "event"}:
        nodes.extend(
            _search_kg_event_nodes(
                db,
                tenant_id=tenant_id,
                allowed_doc_ids=allowed_doc_ids,
                pattern=pattern,
                pipeline_hash=pipeline_hash,
                limit=remaining,
            )
        )

    return nodes[: int(limit)]


@router.get("/stats", response_model=KGStatsResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_kg_stats(
    document_ids: Annotated[list[UUID] | None, Query()] = None,
    dataset_id: Annotated[UUID | None, Query(description=DATASET_SCOPE_FILTER_DESC)] = None,
    pipeline_hash: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=200,
            description=PIPELINE_VERSION_FILTER_DESC,
        ),
    ] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Lightweight KG statistics for the current tenant.

    - Requires KG_ENABLED=true.
    - Enforces document-level access control.
    """
    t0 = time.perf_counter()
    _ensure_enabled()

    allowed_doc_ids = _resolve_allowed_documents(
        document_ids=document_ids,
        dataset_id=dataset_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    if not allowed_doc_ids:
        out = KGStatsResponse(events=0, entities=0, links=0, entity_types=[], updated_at=None)
        _log_kg_api_metric(
            "kg.api.stats",
            tenant_id=str(tenant_id),
            docs=0,
            events=0,
            entities=0,
            links=0,
            elapsed_sec=round(float(time.perf_counter() - t0), 3),
        )
        return out

    from sqlalchemy import func

    from app.rag.kg.models import KgEntity, KgEventEntity, KgSourceEvent

    event_count_q = db.query(func.count(KgSourceEvent.id)).filter(
        KgSourceEvent.tenant_id == tenant_id,
        KgSourceEvent.document_id.in_(allowed_doc_ids),
    )
    event_count_q = _apply_event_pipeline_scope(event_count_q, pipeline_hash=pipeline_hash)
    event_count = event_count_q.scalar() or 0

    link_count_q = (
        db.query(func.count(KgEventEntity.id))
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
        )
    )
    link_count_q = _apply_event_pipeline_scope(link_count_q, pipeline_hash=pipeline_hash)
    link_count = link_count_q.scalar() or 0

    entity_count_q = (
        db.query(func.count(func.distinct(KgEventEntity.entity_id)))
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
        )
    )
    entity_count_q = _apply_event_pipeline_scope(entity_count_q, pipeline_hash=pipeline_hash)
    entity_count = entity_count_q.scalar() or 0

    updated_at_q = db.query(func.max(KgSourceEvent.updated_at)).filter(
        KgSourceEvent.tenant_id == tenant_id,
        KgSourceEvent.document_id.in_(allowed_doc_ids),
    )
    updated_at_q = _apply_event_pipeline_scope(updated_at_q, pipeline_hash=pipeline_hash)
    updated_at = updated_at_q.scalar()

    type_rows_q = (
        db.query(KgEntity.type, func.count(func.distinct(KgEntity.id)).label("cnt"))
        .join(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
        )
    )
    type_rows_q = _apply_event_pipeline_scope(type_rows_q, pipeline_hash=pipeline_hash)
    type_rows = (
        type_rows_q.group_by(KgEntity.type)
        .order_by(func.count(func.distinct(KgEntity.id)).desc(), KgEntity.type.asc())
        .limit(50)
        .all()
    )

    out = KGStatsResponse(
        events=int(event_count),
        entities=int(entity_count),
        links=int(link_count),
        entity_types=[{"type": str(t or "unknown"), "count": int(cnt or 0)} for (t, cnt) in type_rows],
        updated_at=updated_at,
    )
    _log_kg_api_metric(
        "kg.api.stats",
        tenant_id=str(tenant_id),
        docs=len(allowed_doc_ids),
        events=int(event_count),
        entities=int(entity_count),
        links=int(link_count),
        elapsed_sec=round(float(time.perf_counter() - t0), 3),
    )
    return out


@router.post(
    "/imports/preview", response_model=KGManualImportPreviewResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
def preview_manual_kg_import(
    payload: KGManualImportRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Validate a governed external KG payload without writing it to storage."""
    _ensure_enabled()
    DatasetService.ensure_member(db, tenant_id, account_id)
    from app.rag.kg.manual_import import preview_manual_import

    return preview_manual_import(payload)


@router.post("/imports", response_model=KGManualImportResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def import_manual_kg(
    payload: KGManualImportRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Import a manually governed KG payload into MimirQ.

    Domain-specific extraction/rule building should happen outside MimirQ and
    produce this stable import format.
    """
    _ensure_enabled()
    from app.rag.kg.manual_import import apply_manual_import

    return apply_manual_import(db, tenant_id=tenant_id, account_id=account_id, payload=payload)


@router.get("/imports", response_model=KGManualImportListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_manual_kg_imports(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """List manual KG import batches visible to the current account."""
    _ensure_enabled()
    from app.rag.kg.manual_import import list_manual_imports

    return list_manual_imports(db, tenant_id=tenant_id, account_id=account_id, limit=limit)


@router.delete(
    "/imports/{import_id}", response_model=KGManualImportDeleteResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
def delete_manual_kg_import(
    import_id: str,
    prune_entities: Annotated[
        bool, Query(description="Delete entities created only by this import when they become orphaned")
    ] = True,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Rollback a manual KG import batch by import_id."""
    _ensure_enabled()
    from app.rag.kg.manual_import import delete_manual_import

    clean_import_id = str(import_id or "").strip()
    if not clean_import_id:
        raise HTTPException(status_code=400, detail="import_id is required")
    return delete_manual_import(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        import_id=clean_import_id,
        prune_entities=bool(prune_entities),
    )


class KGSnapshotDiffRequest(BaseModel):
    snapshot_a: dict[str, Any]
    snapshot_b: dict[str, Any]


def _empty_kg_snapshot(*, schema: str, pipeline_hash: str, include_details: bool) -> dict[str, Any]:
    return {
        "schema": schema,
        "pipeline_hash": pipeline_hash,
        "docs": 0,
        "events": 0,
        "entities": 0,
        "links": 0,
        "relations": 0,
        "entity_types": [],
        "nodes": [] if include_details else None,
        "edges": [] if include_details else None,
    }


def _kg_snapshot_counts(
    db: Session,
    *,
    tenant_id: UUID,
    allowed_doc_ids: list[UUID],
    pipeline_hash: str,
) -> KGSnapshotCounts:
    from sqlalchemy import func

    from app.rag.kg.models import KgEntity, KgEventEntity, KgRelation, KgSourceEvent

    event_filter = (
        KgSourceEvent.tenant_id == tenant_id,
        KgSourceEvent.document_id.in_(allowed_doc_ids),
        KgSourceEvent.pipeline_hash == pipeline_hash,
    )
    docs_count = db.query(func.count(func.distinct(KgSourceEvent.document_id))).filter(*event_filter).scalar() or 0
    event_count = db.query(func.count(KgSourceEvent.id)).filter(*event_filter).scalar() or 0
    link_count = (
        db.query(func.count(KgEventEntity.id))
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(*event_filter)
        .scalar()
        or 0
    )
    entity_count = (
        db.query(func.count(func.distinct(KgEventEntity.entity_id)))
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(*event_filter)
        .scalar()
        or 0
    )
    relation_count = (
        db.query(func.count(KgRelation.id))
        .filter(
            KgRelation.tenant_id == tenant_id,
            KgRelation.document_id.in_(allowed_doc_ids),
            KgRelation.pipeline_hash == pipeline_hash,
        )
        .scalar()
        or 0
    )
    type_rows = (
        db.query(KgEntity.type, func.count(func.distinct(KgEntity.id)).label("cnt"))
        .join(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(*event_filter)
        .group_by(KgEntity.type)
        .order_by(func.count(func.distinct(KgEntity.id)).desc(), KgEntity.type.asc())
        .limit(50)
        .all()
    )
    return KGSnapshotCounts(
        docs=int(docs_count),
        events=int(event_count),
        entities=int(entity_count),
        links=int(link_count),
        relations=int(relation_count),
        updated_at=db.query(func.max(KgSourceEvent.updated_at)).filter(*event_filter).scalar(),
        entity_types=[{"type": str(t or "unknown"), "count": int(cnt or 0)} for (t, cnt) in type_rows],
    )


def _kg_snapshot_base(*, schema: str, pipeline_hash: str, counts: KGSnapshotCounts, t0: float) -> dict[str, Any]:
    return {
        "schema": schema,
        "pipeline_hash": str(pipeline_hash),
        "docs": counts.docs,
        "events": counts.events,
        "entities": counts.entities,
        "links": counts.links,
        "relations": counts.relations,
        "entity_types": counts.entity_types,
        "updated_at": counts.updated_at,
        "elapsed_sec": round(float(time.perf_counter() - t0), 3),
    }


def _kg_snapshot_detail_rows(
    db: Session,
    *,
    tenant_id: UUID,
    allowed_doc_ids: list[UUID],
    pipeline_hash: str,
    detail_limit: int,
) -> KGSnapshotDetailRows:
    from app.rag.kg.models import KgEntity, KgEventEntity, KgRelation, KgSourceEvent

    event_filter = (
        KgSourceEvent.tenant_id == tenant_id,
        KgSourceEvent.document_id.in_(allowed_doc_ids),
        KgSourceEvent.pipeline_hash == pipeline_hash,
    )
    event_rows = (
        db.query(KgSourceEvent)
        .filter(*event_filter)
        .order_by(KgSourceEvent.updated_at.desc(), KgSourceEvent.id.asc())
        .limit(int(detail_limit))
        .all()
    )
    entity_rows = (
        db.query(KgEntity)
        .join(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(*event_filter)
        .group_by(KgEntity.id)
        .order_by(KgEntity.type.asc(), KgEntity.name.asc(), KgEntity.id.asc())
        .limit(int(detail_limit))
        .all()
    )
    link_rows = (
        db.query(KgEventEntity)
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(*event_filter)
        .order_by(KgEventEntity.id.asc())
        .limit(int(detail_limit))
        .all()
    )
    relation_rows = (
        db.query(KgRelation)
        .filter(
            KgRelation.tenant_id == tenant_id,
            KgRelation.document_id.in_(allowed_doc_ids),
            KgRelation.pipeline_hash == pipeline_hash,
        )
        .order_by(KgRelation.id.asc())
        .limit(int(detail_limit))
        .all()
    )
    return KGSnapshotDetailRows(events=event_rows, entities=entity_rows, links=link_rows, relations=relation_rows)


def _kg_snapshot_event_node(event: Any, canonical_json_hash: Any) -> dict[str, Any]:
    props = {
        "title": event.title,
        "summary": event.summary,
        "document_id": str(event.document_id) if event.document_id else None,
        "chunk_id": str(event.chunk_id) if event.chunk_id else None,
        "extra_data": event.extra_data or {},
    }
    return {
        "id": f"event:{event.id}",
        "kind": "event",
        "type": "event",
        "name": event.title,
        "props_hash": canonical_json_hash(props),
    }


def _kg_snapshot_entity_node(entity: Any, canonical_json_hash: Any) -> dict[str, Any]:
    props = {
        "name": entity.name,
        "type": entity.type,
        "description": entity.description,
        "normalized_name": entity.normalized_name,
        "extra_data": entity.extra_data or {},
    }
    return {
        "id": f"entity:{entity.id}",
        "kind": "entity",
        "type": str(entity.type or "unknown"),
        "name": entity.name,
        "props_hash": canonical_json_hash(props),
    }


def _kg_snapshot_link_edge(link: Any, canonical_json_hash: Any) -> dict[str, Any]:
    props = {"role": link.role, "weight": str(link.weight), "extra_data": link.extra_data or {}}
    return {
        "id": f"event_entity:{link.id}",
        "src": f"event:{link.event_id}",
        "dst": f"entity:{link.entity_id}",
        "kind": "event_entity",
        "predicate": str(link.role or "mentions"),
        "props_hash": canonical_json_hash(props),
    }


def _kg_snapshot_relation_edge(relation: Any, canonical_json_hash: Any) -> dict[str, Any]:
    props = {
        "predicate": relation.predicate,
        "predicate_raw": relation.predicate_raw,
        "confidence": str(relation.confidence),
        "qualifiers": relation.qualifiers or {},
        "references": relation.references or {},
        "extra_data": relation.extra_data or {},
    }
    return {
        "id": f"relation:{relation.id}",
        "src": f"entity:{relation.subject_entity_id}",
        "dst": f"entity:{relation.object_entity_id}",
        "kind": "relation",
        "predicate": relation.predicate,
        "props_hash": canonical_json_hash(props),
    }


def _add_kg_snapshot_details(
    snapshot: dict[str, Any],
    *,
    rows: KGSnapshotDetailRows,
    counts: KGSnapshotCounts,
    detail_limit: int,
    canonical_json_hash: Any,
) -> dict[str, Any]:
    snapshot["nodes"] = [
        *[_kg_snapshot_event_node(event, canonical_json_hash) for event in rows.events],
        *[_kg_snapshot_entity_node(entity, canonical_json_hash) for entity in rows.entities],
    ]
    snapshot["edges"] = [
        *[_kg_snapshot_link_edge(link, canonical_json_hash) for link in rows.links],
        *[_kg_snapshot_relation_edge(relation, canonical_json_hash) for relation in rows.relations],
    ]
    snapshot["detail_limits"] = {"nodes": int(detail_limit), "edges": int(detail_limit)}
    snapshot["detail_truncated"] = {
        "events": counts.events > len(rows.events),
        "entities": counts.entities > len(rows.entities),
        "links": counts.links > len(rows.links),
        "relations": counts.relations > len(rows.relations),
    }
    return snapshot


@router.get("/snapshots/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_kg_snapshot(
    pipeline_hash: Annotated[str, Query(min_length=1, max_length=200)],
    document_ids: Annotated[list[UUID] | None, Query()] = None,
    dataset_id: Annotated[UUID | None, Query(description=DATASET_SCOPE_FILTER_DESC)] = None,
    include_details: Annotated[bool, Query(description="Include bounded node/edge details for exact diff")] = False,
    detail_limit: Annotated[int, Query(ge=1, le=10000, description="Max nodes/edges per detail group")] = 1000,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Export a lightweight KG snapshot for a specific document pipeline_hash.

    This is intended for diagnosing extraction drift across pipeline versions.
    The snapshot is intentionally small and PII-safe by default (counts + type histogram).
    """
    t0 = time.perf_counter()
    _ensure_enabled()

    allowed_doc_ids = _resolve_allowed_documents(
        document_ids=document_ids,
        dataset_id=dataset_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    from app.rag.kg.snapshot import KG_SNAPSHOT_SCHEMA_V1, KG_SNAPSHOT_SCHEMA_V2, canonical_json_hash

    schema = KG_SNAPSHOT_SCHEMA_V2 if include_details else KG_SNAPSHOT_SCHEMA_V1
    if not allowed_doc_ids:
        return _empty_kg_snapshot(schema=schema, pipeline_hash=pipeline_hash, include_details=include_details)

    counts = _kg_snapshot_counts(db, tenant_id=tenant_id, allowed_doc_ids=allowed_doc_ids, pipeline_hash=pipeline_hash)
    snapshot = _kg_snapshot_base(schema=schema, pipeline_hash=pipeline_hash, counts=counts, t0=t0)
    if not include_details:
        return snapshot

    rows = _kg_snapshot_detail_rows(
        db,
        tenant_id=tenant_id,
        allowed_doc_ids=allowed_doc_ids,
        pipeline_hash=pipeline_hash,
        detail_limit=int(detail_limit),
    )
    return _add_kg_snapshot_details(
        snapshot,
        rows=rows,
        counts=counts,
        detail_limit=int(detail_limit),
        canonical_json_hash=canonical_json_hash,
    )


@router.post(
    "/snapshots/diff",
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
    dependencies=[Depends(get_current_account_id)],
)
def diff_kg_snapshots_api(body: KGSnapshotDiffRequest):
    from app.rag.kg.snapshot import diff_kg_snapshots  # noqa: WPS433

    return diff_kg_snapshots(body.snapshot_a, body.snapshot_b)


@router.get("/snapshots/compare", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def compare_kg_snapshots(
    pipeline_hash_a: Annotated[str, Query(min_length=1, max_length=200)],
    pipeline_hash_b: Annotated[str, Query(min_length=1, max_length=200)],
    document_ids: Annotated[list[UUID] | None, Query()] = None,
    dataset_id: Annotated[UUID | None, Query(description=DATASET_SCOPE_FILTER_DESC)] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    from app.rag.kg.snapshot import diff_kg_snapshots  # noqa: WPS433

    snap_a = export_kg_snapshot(
        pipeline_hash=pipeline_hash_a,
        document_ids=document_ids,
        dataset_id=dataset_id,
        include_details=True,
        detail_limit=1000,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    snap_b = export_kg_snapshot(
        pipeline_hash=pipeline_hash_b,
        document_ids=document_ids,
        dataset_id=dataset_id,
        include_details=True,
        detail_limit=1000,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    return diff_kg_snapshots(snap_a, snap_b)


def _add_graphml_key(root: Any, *, key_id: str, kind: str, name: str, typ: str) -> None:
    ET.SubElement(root, "key", {"id": key_id, "for": kind, "attr.name": name, "attr.type": typ})


def _build_graphml_root() -> tuple[Any, Any]:
    graphml_xmlns = "http" + "://graphml.graphdrawing.org/xmlns"
    root = ET.Element("graphml", xmlns=graphml_xmlns)
    for key_id, kind, name, typ in (
        ("d0", "node", "label", "string"),
        ("d1", "node", "kind", "string"),
        ("d2", "node", "type", "string"),
        ("d3", "node", "normalized_name", "string"),
        ("d4", "node", "document_id", "string"),
        ("d5", "node", "chunk_id", "string"),
        ("d6", "node", "group", "int"),
        ("d7", "node", "val", "int"),
        ("e0", "edge", "label", "string"),
        ("e1", "edge", "weight", "double"),
        ("e2", "edge", "kind", "string"),
        ("e3", "edge", "shared_events", "int"),
    ):
        _add_graphml_key(root, key_id=key_id, kind=kind, name=name, typ=typ)
    graph_el = ET.SubElement(root, "graph", {"id": "G", "edgedefault": "directed"})
    return root, graph_el


def _add_graphml_node(graph_el: Any, node: Any) -> None:
    n = ET.SubElement(graph_el, "node", {"id": str(node.id)})
    meta = dict(getattr(node, "meta", {}) or {})
    ET.SubElement(n, "data", {"key": "d0"}).text = str(node.label or node.id)
    ET.SubElement(n, "data", {"key": "d1"}).text = str(meta.get("kind") or "")
    ET.SubElement(n, "data", {"key": "d2"}).text = str(meta.get("type") or "")
    ET.SubElement(n, "data", {"key": "d3"}).text = str(meta.get("normalized_name") or "")
    ET.SubElement(n, "data", {"key": "d4"}).text = str(meta.get("document_id") or "")
    ET.SubElement(n, "data", {"key": "d5"}).text = str(meta.get("chunk_id") or "")
    ET.SubElement(n, "data", {"key": "d6"}).text = str(int(getattr(node, "group", 0) or 0))
    ET.SubElement(n, "data", {"key": "d7"}).text = str(int(getattr(node, "val", 1) or 1))


def _add_graphml_edge(graph_el: Any, idx: int, link: Any) -> None:
    edge = ET.SubElement(
        graph_el,
        "edge",
        {"id": f"e{idx}", "source": str(link.source), "target": str(link.target)},
    )
    meta = dict(getattr(link, "meta", {}) or {})
    ET.SubElement(edge, "data", {"key": "e0"}).text = str(getattr(link, "label", "") or "")
    ET.SubElement(edge, "data", {"key": "e1"}).text = str(float(getattr(link, "weight", 1.0) or 1.0))
    ET.SubElement(edge, "data", {"key": "e2"}).text = str(meta.get("kind") or "")
    ET.SubElement(edge, "data", {"key": "e3"}).text = str(int(meta.get("shared_events") or 0))


def _kg_graphml_payload(graph: KGGraphResponse) -> str:
    root, graph_el = _build_graphml_root()
    for node in graph.nodes:
        _add_graphml_node(graph_el, node)
    for idx, link in enumerate(graph.links):
        _add_graphml_edge(graph_el, idx, link)
    xml_text = ET.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_text}\n'


def _kg_graph_export_content(
    *, payload: str, flags: KGGraphExportFlags, tenant_id: UUID
) -> tuple[str | bytes, dict[str, str]]:
    headers: dict[str, str] = {}
    if flags.download:
        ext = "graphml.gz" if flags.gzip_output else "graphml"
        headers["Content-Disposition"] = f'attachment; filename="mimirq-kg-{tenant_id}.{ext}"'
    if not flags.gzip_output:
        return payload, headers
    headers["Content-Encoding"] = "gzip"
    return gzip.compress(payload.encode("utf-8"), compresslevel=6), headers


def _log_kg_graph_export(
    *,
    t0: float,
    tenant_id: UUID,
    params: KGGraphProjectionParams,
    graph: KGGraphResponse,
    flags: KGGraphExportFlags,
    content: str | bytes,
) -> None:
    export_stats = dict(getattr(graph, "stats", {}) or {})
    _log_kg_api_metric(
        "kg.api.graph_export",
        tenant_id=str(tenant_id),
        docs_requested=(len(params.document_ids) if params.document_ids is not None else None),
        events=int(export_stats.get("events", 0) or 0),
        entities=int(export_stats.get("entities", 0) or 0),
        links=int(export_stats.get("links", 0) or 0),
        gzip=bool(flags.gzip_output),
        bytes=len(content) if isinstance(content, (bytes, bytearray)) else len(content.encode("utf-8")),
        elapsed_sec=round(float(time.perf_counter() - t0), 3),
    )


@router.get("/graph/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_kg_graph(
    params: Annotated[KGGraphProjectionParams, Depends(kg_graph_projection_params)],
    flags: Annotated[KGGraphExportFlags, Depends(kg_graph_export_flags)],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Export KG graph projection as GraphML for external tooling.

    Uses the same access control and projection logic as `GET /kg/graph`.
    """
    t0 = time.perf_counter()
    graph = get_kg_graph(
        params=params,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    payload = _kg_graphml_payload(graph)
    media_type = "application/graphml+xml"
    content, headers = _kg_graph_export_content(payload=payload, flags=flags, tenant_id=tenant_id)
    _log_kg_graph_export(t0=t0, tenant_id=tenant_id, params=params, graph=graph, flags=flags, content=content)

    return Response(content=content, media_type=media_type, headers=headers)


@router.get("/events/{event_id}", response_model=KGEventDetailResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_kg_event_detail(
    event_id: UUID,
    document_ids: Annotated[list[UUID] | None, Query()] = None,
    dataset_id: Annotated[UUID | None, Query(description=DATASET_SCOPE_FILTER_DESC)] = None,
    pipeline_hash: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=200,
            description=PIPELINE_VERSION_FILTER_DESC,
        ),
    ] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Get a KG event with its linked entities (scoped to accessible documents)."""
    _ensure_enabled()

    allowed_doc_ids = _resolve_allowed_documents(
        document_ids=document_ids,
        dataset_id=dataset_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    if not allowed_doc_ids:
        raise HTTPException(status_code=404, detail="No accessible documents")

    from app.rag.kg.models import KgEntity, KgEventEntity, KgSourceEvent
    from app.rag.kg.provenance import build_event_entity_provenance

    ev_q = db.query(KgSourceEvent).filter(
        KgSourceEvent.tenant_id == tenant_id,
        KgSourceEvent.id == event_id,
        KgSourceEvent.document_id.in_(allowed_doc_ids),
    )
    ev_q = _apply_event_pipeline_scope(ev_q, pipeline_hash=pipeline_hash)
    ev = ev_q.first()
    if not ev:
        raise HTTPException(status_code=404, detail="KG event not found")

    rows = (
        db.query(KgEventEntity, KgEntity)
        .join(KgEntity, KgEntity.id == KgEventEntity.entity_id)
        .filter(KgEventEntity.event_id == ev.id)
        .all()
    )
    entities = [
        KGEventEntityItem(
            entity=KGEntityItem.model_validate(ent),
            weight=float(getattr(assoc, "weight", 1.0) or 1.0),
            role=(getattr(assoc, "role", None) or None),
            extra_data=build_event_entity_provenance(
                document_id=(
                    getattr(assoc, "extra_data", None).get("document_id")
                    if isinstance(getattr(assoc, "extra_data", None), dict)
                    else getattr(ev, "document_id", None)
                ),
                chunk_id=(
                    getattr(assoc, "extra_data", None).get("chunk_id")
                    if isinstance(getattr(assoc, "extra_data", None), dict)
                    else getattr(ev, "chunk_id", None)
                ),
                references=(
                    getattr(assoc, "extra_data", None)
                    if isinstance(getattr(assoc, "extra_data", None), dict)
                    else (
                        getattr(ev, "references", None) if isinstance(getattr(ev, "references", None), dict) else None
                    )
                ),
            ),
        )
        for assoc, ent in rows
        if ent is not None
    ]

    return KGEventDetailResponse(event=KGEventItem.model_validate(ev), entities=entities)


@router.get("/entities/{entity_id}", response_model=KGEntityDetailResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_kg_entity_detail(
    entity_id: UUID,
    document_ids: Annotated[list[UUID] | None, Query()] = None,
    dataset_id: Annotated[UUID | None, Query(description=DATASET_SCOPE_FILTER_DESC)] = None,
    pipeline_hash: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=200,
            description=PIPELINE_VERSION_FILTER_DESC,
        ),
    ] = None,
    max_events: Annotated[int, Query(ge=1, le=200)] = 30,
    max_neighbors: Annotated[int, Query(ge=0, le=200)] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Get a KG entity, its recent events, and co-occurring entity neighbors."""
    _ensure_enabled()

    resolved_entity_id = _resolve_entity_id_via_redirects(db=db, tenant_id=tenant_id, entity_id=entity_id)
    entity_id = resolved_entity_id

    allowed_doc_ids = _resolve_allowed_documents(
        document_ids=document_ids,
        dataset_id=dataset_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    if not allowed_doc_ids:
        raise HTTPException(status_code=404, detail="No accessible documents")

    from sqlalchemy import desc, func

    from app.rag.kg.models import KgEntity, KgEventEntity, KgSourceEvent

    ent = db.query(KgEntity).filter(KgEntity.tenant_id == tenant_id, KgEntity.id == entity_id).first()
    if not ent:
        raise HTTPException(status_code=404, detail=KG_ENTITY_NOT_FOUND_DETAIL)

    total_events_q = (
        db.query(func.count(func.distinct(KgEventEntity.event_id)))
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
            KgEventEntity.entity_id == entity_id,
        )
    )
    total_events_q = _apply_event_pipeline_scope(total_events_q, pipeline_hash=pipeline_hash)
    total_events = total_events_q.scalar() or 0
    if not total_events:
        raise HTTPException(status_code=404, detail=KG_ENTITY_NOT_FOUND_DETAIL)

    events_q = (
        db.query(KgSourceEvent)
        .join(KgEventEntity, KgEventEntity.event_id == KgSourceEvent.id)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
            KgEventEntity.entity_id == entity_id,
        )
    )
    events_q = _apply_event_pipeline_scope(events_q, pipeline_hash=pipeline_hash)
    events = events_q.order_by(desc(KgSourceEvent.updated_at)).limit(int(max_events)).all()
    event_ids = [e.id for e in events]

    neighbors = []
    if event_ids and int(max_neighbors) > 0:
        cnt_expr = func.count(func.distinct(KgEventEntity.event_id)).label("cnt")
        rows = (
            db.query(
                KgEntity.id,
                KgEntity.name,
                KgEntity.type,
                cnt_expr,
            )
            .join(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
            .filter(KgEventEntity.event_id.in_(event_ids))
            .filter(KgEntity.tenant_id == tenant_id)
            .filter(KgEntity.id != entity_id)
            .group_by(KgEntity.id, KgEntity.name, KgEntity.type)
            .order_by(cnt_expr.desc(), KgEntity.id.asc())
            .limit(int(max_neighbors))
            .all()
        )
        neighbors = [
            {"entity_id": row[0], "name": row[1] or "", "type": row[2] or "unknown", "count": int(row[3] or 0)}
            for row in rows
            if row and row[0]
        ]

    return KGEntityDetailResponse(
        entity=KGEntityItem.model_validate(ent),
        events=[KGEventItem.model_validate(ev) for ev in events],
        neighbors=neighbors,
        stats={"total_events": int(total_events), "returned_events": len(events), "returned_neighbors": len(neighbors)},
    )


@router.get(
    "/entities/{entity_id}/aliases", response_model=KGEntityAliasesResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
def list_kg_entity_aliases(
    entity_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    _account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """List aliases for an entity (includes aliases attached to redirected source ids)."""
    _ensure_enabled()

    from sqlalchemy import or_  # noqa: WPS433

    from app.rag.kg.models import KgEntity, KgEntityAlias, KgEntityRedirect

    resolved_id = _resolve_entity_id_via_redirects(db=db, tenant_id=tenant_id, entity_id=entity_id)

    ent = db.query(KgEntity).filter_by(tenant_id=tenant_id, id=resolved_id).first()
    if not ent:
        raise HTTPException(status_code=404, detail=KG_ENTITY_NOT_FOUND_DETAIL)

    # Include aliases attached to merged/deprecated ids that redirect into this canonical entity.
    redirect_rows = db.query(KgEntityRedirect).filter_by(tenant_id=tenant_id, to_entity_id=resolved_id).all()
    alias_entity_ids = {resolved_id}
    for r in redirect_rows:
        frm = getattr(r, "from_entity_id", None)
        if frm is not None:
            alias_entity_ids.add(frm)

    rows = (
        db.query(KgEntityAlias)
        .filter(KgEntityAlias.tenant_id == tenant_id)
        .filter(KgEntityAlias.canonical_entity_id.in_(list(alias_entity_ids)))
        .filter(or_(KgEntityAlias.alias.isnot(None), KgEntityAlias.alias != ""))  # sanity
        .order_by(KgEntityAlias.updated_at.desc(), KgEntityAlias.id.asc())
        .limit(500)
        .all()
    )

    return KGEntityAliasesResponse(
        entity_id=entity_id,
        resolved_entity_id=resolved_id,
        aliases=[KGEntityAliasItem.model_validate(a) for a in rows],
    )


@router.post(
    "/entities/{entity_id}/aliases", response_model=KGEntityAliasItem, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
def create_kg_entity_alias(
    entity_id: UUID,
    payload: KGEntityAliasCreateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create (or return existing) alias for an entity."""
    _ensure_enabled()

    from datetime import datetime

    from app.models.audit_log import AuditLog
    from app.rag.kg.extraction.parser import EntityValueParser
    from app.rag.kg.models import KgEntity, KgEntityAlias

    resolved_id = _resolve_entity_id_via_redirects(db=db, tenant_id=tenant_id, entity_id=entity_id)
    ent = db.query(KgEntity).filter_by(tenant_id=tenant_id, id=resolved_id).first()
    if not ent:
        raise HTTPException(status_code=404, detail=KG_ENTITY_NOT_FOUND_DETAIL)

    alias_text = str(payload.alias or "").strip()
    if not alias_text:
        raise HTTPException(status_code=400, detail="alias is required")

    parser = EntityValueParser()
    norm = parser.normalize_name(alias_text)
    if not norm:
        raise HTTPException(status_code=400, detail="alias normalizes to empty")

    existing = (
        db.query(KgEntityAlias)
        .filter_by(tenant_id=tenant_id, canonical_entity_id=resolved_id, normalized_alias=norm)
        .first()
    )
    if existing:
        return KGEntityAliasItem.model_validate(existing)

    alias_row = KgEntityAlias(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        canonical_entity_id=resolved_id,
        alias=alias_text[:500],
        normalized_alias=norm[:500],
        created_by=str(account_id or "").strip() or None,
        extra_data={"method": "manual"},
        created_at=datetime.now(UTC).replace(tzinfo=None),
        updated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(alias_row)

    try:
        db.add(
            AuditLog(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                actor_id=str(account_id or "").strip() or None,
                action="kg.entity.alias.create",
                resource_type="kg_entity",
                resource_id=str(resolved_id),
                details={
                    "alias_hash": _audit_hash_text(alias_text),
                    "alias_chars": int(len(alias_text)),
                    "normalized_alias_hash": _audit_hash_text(norm),
                    "normalized_alias_chars": int(len(norm)),
                },
            )
        )
    except Exception as exc:
        logger.debug(KG_API_FALLBACK_LOG_MESSAGE, exc)

    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug(KG_API_FALLBACK_LOG_MESSAGE, exc)
        raise

    return KGEntityAliasItem.model_validate(alias_row)


@router.delete(
    "/entities/{entity_id}/aliases/{alias_id}",
    response_model=KGEntityAliasesResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def delete_kg_entity_alias(
    entity_id: UUID,
    alias_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Delete an alias row by id (best-effort, tenant-scoped)."""
    _ensure_enabled()

    from app.models.audit_log import AuditLog
    from app.rag.kg.models import KgEntityAlias

    resolved_id = _resolve_entity_id_via_redirects(db=db, tenant_id=tenant_id, entity_id=entity_id)

    row = db.query(KgEntityAlias).filter_by(tenant_id=tenant_id, id=alias_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Alias not found")

    db.delete(row)
    try:
        db.add(
            AuditLog(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                actor_id=str(account_id or "").strip() or None,
                action="kg.entity.alias.delete",
                resource_type="kg_entity",
                resource_id=str(resolved_id),
                details={"alias_id": str(alias_id)},
            )
        )
    except Exception as exc:
        logger.debug(KG_API_FALLBACK_LOG_MESSAGE, exc)

    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug(KG_API_FALLBACK_LOG_MESSAGE, exc)
        raise

    # Return the current alias set after deletion.
    return list_kg_entity_aliases(entity_id=entity_id, tenant_id=tenant_id, account_id=account_id, db=db)


@router.get(
    "/entities/{entity_id}/alias_suggestions",
    response_model=KGEntityAliasSuggestionsResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def suggest_kg_entity_aliases(
    entity_id: UUID,
    mode: Annotated[str, Query(min_length=1, max_length=16, description="offline|vector")] = "offline",
    k: Annotated[int, Query(ge=1, le=50)] = 10,
    min_similarity: Annotated[float, Query(ge=0.0, le=1.0)] = 0.6,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    _account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Suggest potential aliases/merge candidates for an entity."""
    _ensure_enabled()

    from app.rag.kg.models import KgEntity

    resolved_id = _resolve_entity_id_via_redirects(db=db, tenant_id=tenant_id, entity_id=entity_id)
    ent = db.query(KgEntity).filter_by(tenant_id=tenant_id, id=resolved_id).first()
    if not ent:
        raise HTTPException(status_code=404, detail=KG_ENTITY_NOT_FOUND_DETAIL)

    eff_mode = (mode or "offline").strip().lower()
    want_k = int(k)

    if eff_mode == "offline" or not bool(getattr(ent, "vector", None)):
        return _offline_alias_suggestions(
            db,
            KgEntity,
            tenant_id=tenant_id,
            entity=ent,
            resolved_id=resolved_id,
            want_k=want_k,
            min_similarity=float(min_similarity),
        )

    return _vector_alias_suggestions(db, tenant_id=tenant_id, entity=ent, resolved_id=resolved_id, want_k=want_k)


@router.post(
    "/entities/merge/preview", response_model=KGEntityMergePreviewResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
def preview_kg_entity_merge(
    payload: KGEntityMergeRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    _account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Preview the impact of merging one entity into another (no side effects)."""
    _ensure_enabled()

    from app.rag.kg.models import KgEntity, KgEventEntity, KgRelation

    source_id = _resolve_entity_id_via_redirects(db=db, tenant_id=tenant_id, entity_id=payload.source_entity_id)
    target_id = _resolve_entity_id_via_redirects(db=db, tenant_id=tenant_id, entity_id=payload.target_entity_id)
    if source_id == target_id:
        raise HTTPException(status_code=400, detail="Entities already resolve to the same canonical id")

    source_ent = db.query(KgEntity).filter_by(tenant_id=tenant_id, id=source_id).first()
    target_ent = db.query(KgEntity).filter_by(tenant_id=tenant_id, id=target_id).first()
    if not source_ent or not target_ent:
        raise HTTPException(status_code=404, detail=KG_ENTITY_NOT_FOUND_DETAIL)

    source_assocs = db.query(KgEventEntity).filter_by(entity_id=source_id).all()
    target_assocs = db.query(KgEventEntity).filter_by(entity_id=target_id).all()
    source_event_ids = {getattr(a, "event_id", None) for a in source_assocs if getattr(a, "event_id", None) is not None}
    target_event_ids = {getattr(a, "event_id", None) for a in target_assocs if getattr(a, "event_id", None) is not None}
    overlap_events = source_event_ids.intersection(target_event_ids)

    sample_n = 20
    source_event_sample = [str(e) for e in sorted(source_event_ids, key=lambda x: str(x))[:sample_n]]
    overlap_event_sample = [str(e) for e in sorted(overlap_events, key=lambda x: str(x))[:sample_n]]

    rel_rows = []
    rel_rows.extend(db.query(KgRelation).filter_by(tenant_id=tenant_id, subject_entity_id=source_id).all())
    rel_rows.extend(db.query(KgRelation).filter_by(tenant_id=tenant_id, object_entity_id=source_id).all())
    rel_by_id: dict[str, object] = {}
    for r in rel_rows:
        rid = str(getattr(r, "id", "") or "")
        if rid:
            rel_by_id[rid] = r

    self_rel_after = 0
    for r in rel_by_id.values():
        subj = getattr(r, "subject_entity_id", None)
        obj = getattr(r, "object_entity_id", None)
        if (subj == source_id and obj == target_id) or (subj == target_id and obj == source_id):
            self_rel_after += 1

    return KGEntityMergePreviewResponse(
        source_entity_id=source_id,
        target_entity_id=target_id,
        stats={
            "source_event_entity_edges": len(source_assocs),
            "target_event_entity_edges": len(target_assocs),
            "overlap_events": len(overlap_events),
            "source_relations": len(rel_by_id),
            "self_relations_removed": int(self_rel_after),
            # Preview details (bounded) for UI conflict resolution workflows.
            "source_events": int(len(source_event_ids)),
            "source_event_ids_sample": source_event_sample,
            "overlap_event_ids_sample": overlap_event_sample,
            # Merge semantics: overlapping events will trigger a dedupe delete of the source association.
            "event_entity_edges_deleted": int(len(overlap_events)),
            "event_entity_edges_updated": int(max(0, len(source_assocs) - len(overlap_events))),
        },
    )


@router.get(
    "/ontology/predicates", response_model=KGPredicateOntologyListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
def list_kg_predicate_ontology(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    _account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """List predicate ontology entries (tenant-scoped)."""
    _ensure_enabled()

    from app.rag.kg.models import KgPredicateOntology

    rows = (
        db.query(KgPredicateOntology)
        .filter_by(tenant_id=tenant_id)
        .order_by(KgPredicateOntology.is_enabled.desc(), KgPredicateOntology.predicate.asc())
        .all()
    )
    return KGPredicateOntologyListResponse(predicates=[KGPredicateOntologyItem.model_validate(r) for r in rows])


@router.post(
    "/ontology/predicates", response_model=KGPredicateOntologyItem, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
def create_kg_predicate_ontology(
    payload: KGPredicateOntologyCreateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create (or upsert) a predicate ontology entry."""
    _ensure_enabled()

    from datetime import datetime

    from app.models.audit_log import AuditLog
    from app.rag.kg.extraction.relation_processor import normalize_predicate
    from app.rag.kg.models import KgPredicateOntology

    key = normalize_predicate(str(payload.predicate or ""))
    if not key or key == "unknown":
        raise HTTPException(status_code=400, detail="Invalid predicate key")

    existing = db.query(KgPredicateOntology).filter_by(tenant_id=tenant_id, predicate=key).first()
    if existing:
        existing.display_name = payload.display_name
        existing.description = payload.description
        existing.is_enabled = bool(payload.is_enabled)
        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
        row = existing
    else:
        row = KgPredicateOntology(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            predicate=key[:200],
            display_name=(str(payload.display_name)[:200] if payload.display_name else None),
            description=(str(payload.description) if payload.description else None),
            is_enabled=bool(payload.is_enabled),
            extra_data={"source": "ui"},
            created_at=datetime.now(UTC).replace(tzinfo=None),
            updated_at=datetime.now(UTC).replace(tzinfo=None),
        )
        db.add(row)

    try:
        db.add(
            AuditLog(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                actor_id=str(account_id or "").strip() or None,
                action="kg.ontology.predicate.upsert",
                resource_type="kg_predicate_ontology",
                resource_id=str(getattr(row, "id", "")),
                details={"predicate": key, "is_enabled": bool(payload.is_enabled)},
            )
        )
    except Exception as exc:
        logger.debug(KG_API_FALLBACK_LOG_MESSAGE, exc)

    try:
        db.commit()
        db.refresh(row)
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug(KG_API_FALLBACK_LOG_MESSAGE, exc)
        raise

    return KGPredicateOntologyItem.model_validate(row)


@router.patch(
    "/ontology/predicates/{predicate_id}",
    response_model=KGPredicateOntologyItem,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def update_kg_predicate_ontology(
    predicate_id: UUID,
    payload: KGPredicateOntologyUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Update a predicate ontology entry (toggle enabled, edit metadata)."""
    _ensure_enabled()

    from datetime import datetime

    from app.models.audit_log import AuditLog
    from app.rag.kg.models import KgPredicateOntology

    row = db.query(KgPredicateOntology).filter_by(tenant_id=tenant_id, id=predicate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Predicate not found")

    if payload.display_name is not None:
        row.display_name = str(payload.display_name)[:200] if payload.display_name else None
    if payload.description is not None:
        row.description = str(payload.description) if payload.description else None
    if payload.is_enabled is not None:
        row.is_enabled = bool(payload.is_enabled)
    row.updated_at = datetime.now(UTC).replace(tzinfo=None)

    try:
        db.add(
            AuditLog(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                actor_id=str(account_id or "").strip() or None,
                action="kg.ontology.predicate.update",
                resource_type="kg_predicate_ontology",
                resource_id=str(predicate_id),
                details={"is_enabled": payload.is_enabled},
            )
        )
    except Exception as exc:
        logger.debug(KG_API_FALLBACK_LOG_MESSAGE, exc)

    try:
        db.commit()
        db.refresh(row)
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug(KG_API_FALLBACK_LOG_MESSAGE, exc)
        raise

    return KGPredicateOntologyItem.model_validate(row)


@router.delete(
    "/ontology/predicates/{predicate_id}",
    response_model=KGPredicateOntologyListResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def delete_kg_predicate_ontology(
    predicate_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Delete a predicate ontology entry."""
    _ensure_enabled()

    from app.models.audit_log import AuditLog
    from app.rag.kg.models import KgPredicateOntology

    row = db.query(KgPredicateOntology).filter_by(tenant_id=tenant_id, id=predicate_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Predicate not found")

    pred = str(getattr(row, "predicate", "") or "")
    db.delete(row)

    try:
        db.add(
            AuditLog(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                actor_id=str(account_id or "").strip() or None,
                action="kg.ontology.predicate.delete",
                resource_type="kg_predicate_ontology",
                resource_id=str(predicate_id),
                details={"predicate": pred},
            )
        )
    except Exception as exc:
        logger.debug(KG_API_FALLBACK_LOG_MESSAGE, exc)

    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug(KG_API_FALLBACK_LOG_MESSAGE, exc)
        raise

    # Return updated list for convenience in the UI.
    return list_kg_predicate_ontology(tenant_id=tenant_id, account_id=account_id, db=db)


@router.post("/entities/merge", response_model=KGEntityMergeResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def merge_kg_entities(
    payload: KGEntityMergeRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Merge a source entity into a target entity (entity resolution).

    Semantics:
    - Updates event-entity edges and relations to point at the target entity.
    - Creates a redirect so old entity ids resolve to the canonical entity.
    - Dedupes duplicate event-entity edges created by the merge.
    - Records an undo payload in `kg_entity_resolution_actions`.
    """
    _ensure_enabled()

    from app.models.audit_log import AuditLog
    from app.rag.kg.models import (
        KgEntity,
        KgEntityRedirect,
        KgEntityResolutionAction,
        KgEventEntity,
        KgRelation,
    )

    targets = _merge_targets(
        db,
        KgEntity,
        tenant_id=tenant_id,
        source_raw=payload.source_entity_id,
        target_raw=payload.target_entity_id,
    )
    affected = _merge_affected_rows(
        db,
        tenant_id=tenant_id,
        source_id=targets.source_id,
        event_entity_model=KgEventEntity,
        relation_model=KgRelation,
    )
    action = _create_merge_action(
        KgEntityResolutionAction,
        tenant_id=tenant_id,
        account_id=account_id,
        targets=targets,
        affected=affected,
    )
    db.add(action)

    _add_resolution_audit_log(
        db,
        AuditLog,
        tenant_id=tenant_id,
        account_id=account_id,
        action="kg.entity.merge",
        resource_type="kg_entity",
        resource_id=str(targets.target_id),
        details={"source_entity_id": str(targets.source_id), "target_entity_id": str(targets.target_id)},
    )
    redirect_created = _ensure_merge_redirect(
        db,
        KgEntityRedirect,
        tenant_id=tenant_id,
        account_id=account_id,
        source_id=targets.source_id,
        target_id=targets.target_id,
        action_id=action.id,
    )

    for assoc in affected.source_assocs:
        assoc.entity_id = targets.target_id
    relation_deleted_rows = _apply_merge_relation_updates(
        source_id=targets.source_id,
        target_id=targets.target_id,
        affected=affected,
        db=db,
    )
    deleted_assoc_rows = _dedupe_merged_event_entity_edges(
        db,
        KgEventEntity,
        source_id=targets.source_id,
        target_id=targets.target_id,
        affected=affected,
    )
    vector_deleted = _delete_source_entity_vector_if_enabled(targets.source_id)

    # Update the action payload with side effects so undo can restore state.
    payload_dict = dict(action.payload or {})
    payload_dict["event_entity_deleted_rows"] = deleted_assoc_rows
    payload_dict["relation_deleted_rows"] = relation_deleted_rows
    payload_dict["redirect_created"] = bool(redirect_created)
    payload_dict["vector_deleted"] = bool(vector_deleted)
    action.payload = payload_dict

    _commit_or_rollback(db)

    return KGEntityMergeResponse(
        action_id=action.id,
        source_entity_id=targets.source_id,
        target_entity_id=targets.target_id,
        stats={
            "source_event_entity_edges": len(affected.source_assocs),
            "source_relations": len(affected.source_relations),
            "dedup_deleted_event_entity_edges": len(deleted_assoc_rows),
            "deleted_relations": len(relation_deleted_rows),
            "redirect_created": bool(redirect_created),
            "vector_deleted": bool(vector_deleted),
        },
    )


def _validated_split_event_ids(payload: KGEntitySplitRequest) -> list[UUID]:
    event_ids = [event_id for event_id in (payload.event_ids or []) if event_id is not None]
    if not event_ids:
        raise HTTPException(status_code=400, detail="event_ids is required for split")
    if len(event_ids) > 5000:
        raise HTTPException(status_code=400, detail="Too many event_ids (max 5000)")
    return event_ids


def _split_new_entity_name(payload: KGEntitySplitRequest) -> str:
    new_name = str(payload.new_entity_name or "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="new_entity_name is required")
    return new_name


def _create_split_entity(
    entity_model: Any,
    *,
    tenant_id: UUID,
    source_entity: Any,
    new_name: str,
    new_norm: str,
    original_id: UUID,
) -> tuple[UUID, Any]:
    from datetime import datetime

    new_entity_id = uuid.uuid4()
    new_entity = entity_model(
        id=new_entity_id,
        tenant_id=tenant_id,
        name=new_name,
        type=str(getattr(source_entity, "type", "") or "unknown"),
        normalized_name=new_norm,
        description=None,
        vector=None,
        extra_data={"split_from": str(original_id)},
        created_at=datetime.now(UTC).replace(tzinfo=None),
        updated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    return new_entity_id, new_entity


def _move_split_associations(source_assocs: list[Any], *, event_id_set: set[UUID], new_entity_id: UUID) -> list[str]:
    moved_assoc_ids: list[str] = []
    for assoc in source_assocs:
        event_id = getattr(assoc, "event_id", None)
        if event_id is None or event_id not in event_id_set:
            continue
        moved_assoc_ids.append(str(getattr(assoc, "id", "") or ""))
        assoc.entity_id = new_entity_id
    return moved_assoc_ids


def _move_split_relations(
    relations: list[Any],
    *,
    event_id_set: set[UUID],
    original_id: UUID,
    new_entity_id: UUID,
) -> list[str]:
    moved_relation_ids: list[str] = []
    for relation in relations:
        event_id = getattr(relation, "event_id", None)
        if event_id is None or event_id not in event_id_set:
            continue
        moved_relation_ids.append(str(getattr(relation, "id", "") or ""))
        if getattr(relation, "subject_entity_id", None) == original_id:
            relation.subject_entity_id = new_entity_id
        if getattr(relation, "object_entity_id", None) == original_id:
            relation.object_entity_id = new_entity_id
    return moved_relation_ids


def _create_split_action(
    action_model: Any,
    *,
    tenant_id: UUID,
    account_id: str,
    original_id: UUID,
    new_entity_id: UUID,
    moved_assoc_ids: list[str],
    moved_relation_ids: list[str],
    new_name: str,
    event_ids: list[UUID],
) -> Any:
    from datetime import datetime

    return action_model(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        actor_id=str(account_id or "").strip() or None,
        action_type="split",
        status="applied",
        payload={
            "version": 1,
            "action": "split",
            "original_entity_id": str(original_id),
            "new_entity_id": str(new_entity_id),
            "moved_event_entity_ids": [item for item in moved_assoc_ids if item],
            "moved_relation_ids": [item for item in moved_relation_ids if item],
            "new_entity_name": new_name,
            "moved_events": [str(event_id) for event_id in event_ids],
        },
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )


@router.post("/entities/split", response_model=KGEntitySplitResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def split_kg_entity(
    payload: KGEntitySplitRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Split an entity by moving a selected set of event-entity edges to a new entity.

    This is a conservative v1 split:
    - Caller must provide explicit event_ids to move.
    - The new entity inherits the original entity type.
    - Relations are moved only when they are anchored to those event_ids.
    """
    _ensure_enabled()

    from app.models.audit_log import AuditLog
    from app.rag.kg.extraction.parser import EntityValueParser
    from app.rag.kg.models import KgEntity, KgEntityResolutionAction, KgEventEntity, KgRelation

    original_raw = payload.entity_id
    original_id = _resolve_entity_id_via_redirects(db=db, tenant_id=tenant_id, entity_id=original_raw)

    ent = db.query(KgEntity).filter_by(tenant_id=tenant_id, id=original_id).first()
    if not ent:
        raise HTTPException(status_code=404, detail=KG_ENTITY_NOT_FOUND_DETAIL)

    event_ids = _validated_split_event_ids(payload)
    event_id_set = set(event_ids)
    new_name = _split_new_entity_name(payload)
    parser = EntityValueParser()
    new_norm = parser.normalize_name(new_name)
    new_entity_id, new_ent = _create_split_entity(
        KgEntity,
        tenant_id=tenant_id,
        source_entity=ent,
        new_name=new_name,
        new_norm=new_norm,
        original_id=original_id,
    )
    db.add(new_ent)

    source_assocs = db.query(KgEventEntity).filter_by(entity_id=original_id).all()
    moved_assoc_ids = _move_split_associations(source_assocs, event_id_set=event_id_set, new_entity_id=new_entity_id)
    relation_rows = _entity_relation_rows(db, KgRelation, tenant_id=tenant_id, entity_id=original_id)
    moved_relation_ids = _move_split_relations(
        relation_rows,
        event_id_set=event_id_set,
        original_id=original_id,
        new_entity_id=new_entity_id,
    )
    action = _create_split_action(
        KgEntityResolutionAction,
        tenant_id=tenant_id,
        account_id=account_id,
        original_id=original_id,
        new_entity_id=new_entity_id,
        moved_assoc_ids=moved_assoc_ids,
        moved_relation_ids=moved_relation_ids,
        new_name=new_name,
        event_ids=event_ids,
    )
    db.add(action)

    moved_assoc_count = len([item for item in moved_assoc_ids if item])
    moved_relation_count = len([item for item in moved_relation_ids if item])
    _add_resolution_audit_log(
        db,
        AuditLog,
        tenant_id=tenant_id,
        account_id=account_id,
        action="kg.entity.split",
        resource_type="kg_entity",
        resource_id=str(original_id),
        details={
            "original_entity_id": str(original_id),
            "new_entity_id": str(new_entity_id),
            "moved_event_entity_edges": moved_assoc_count,
            "moved_relations": moved_relation_count,
        },
    )
    _commit_or_rollback(db)

    return KGEntitySplitResponse(
        action_id=action.id,
        original_entity_id=original_id,
        new_entity_id=new_entity_id,
        stats={
            "moved_event_entity_edges": moved_assoc_count,
            "moved_relations": moved_relation_count,
        },
    )


@router.post(
    "/entities/resolution/actions/{action_id}/undo",
    response_model=KGEntityResolutionUndoResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def undo_kg_entity_resolution_action(
    action_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Undo a merge/split resolution action (best-effort, deterministic)."""
    _ensure_enabled()

    from datetime import datetime

    from app.models.audit_log import AuditLog
    from app.rag.kg.models import KgEntityRedirect, KgEntityResolutionAction, KgEventEntity, KgRelation

    action = _get_applied_resolution_action(db, KgEntityResolutionAction, tenant_id=tenant_id, action_id=action_id)
    payload = dict(getattr(action, "payload", None) or {})
    action_kind = _resolution_action_kind(payload)
    if action_kind == "merge":
        stats = _undo_merge_resolution_action(
            db,
            tenant_id=tenant_id,
            payload=payload,
            redirect_model=KgEntityRedirect,
            event_entity_model=KgEventEntity,
            relation_model=KgRelation,
        )
    else:
        stats = _undo_split_resolution_action(
            db,
            tenant_id=tenant_id,
            payload=payload,
            redirect_model=KgEntityRedirect,
            event_entity_model=KgEventEntity,
            relation_model=KgRelation,
        )

    action.status = "reverted"
    action.reversed_at = datetime.now(UTC).replace(tzinfo=None)
    action.reversed_by = str(account_id or "").strip() or None

    _add_resolution_audit_log(
        db,
        AuditLog,
        tenant_id=tenant_id,
        account_id=account_id,
        action="kg.entity.merge.undo" if action_kind == "merge" else "kg.entity.split.undo",
        resource_type="kg_entity_resolution_action",
        resource_id=str(action_id),
        details={"source_entity_id": str(stats.source_id), "target_entity_id": str(stats.target_id)},
    )
    _commit_or_rollback(db)

    return KGEntityResolutionUndoResponse(
        action_id=action.id,
        status=str(action.status or ""),
        stats={
            "restored_event_entity_edges": int(stats.restored_edges),
            "restored_relations": int(stats.restored_relations),
            "redirect_removed": bool(stats.redirect_removed),
            "deleted_new_entity": bool(stats.deleted_new_entity),
        },
    )


@router.delete("/documents/{document_id}", response_model=KGDeleteResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def delete_kg_for_document(
    document_id: UUID,
    prune_orphan_entities: Annotated[bool | None, Query()] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Delete KG events for a document (and optionally prune orphan entities)."""
    _ensure_enabled()
    filter_allowed_document_ids(db, tenant_id, account_id, [document_id])

    eff_prune_orphans = bool(
        settings.KG_EXTRACT_PRUNE_ORPHAN_ENTITIES if prune_orphan_entities is None else prune_orphan_entities
    )

    from app.services.indexer import Indexer

    # Best-effort: also delete relation edges derived from this document so pruning can
    # correctly remove orphan entities after event deletion.
    try:
        from app.rag.kg.models import KgRelation

        db.query(KgRelation).filter(
            KgRelation.tenant_id == tenant_id,
            KgRelation.document_id == document_id,
        ).delete(synchronize_session=False)
        db.flush()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug(KG_API_FALLBACK_LOG_MESSAGE, exc)

    stats = Indexer(db).delete_event_indexes(
        tenant_id=tenant_id,
        document_id=document_id,
        prune_orphan_entities=eff_prune_orphans,
    )

    # Best-effort audit log (PII-minimal): record KG deletion per document.
    try:
        from app.models.audit_log import AuditLog

        details: dict[str, Any] = {
            "document_id": str(document_id),
            "prune_orphan_entities": bool(eff_prune_orphans),
        }
        if isinstance(stats, dict):
            for k, v in stats.items():
                try:
                    details[str(k)[:64]] = int(v)  # type: ignore[arg-type]
                except Exception:
                    get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                    continue

        db.add(
            AuditLog(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                actor_id=str(account_id or "").strip() or None,
                action="kg.document.delete",
                resource_type="document",
                resource_id=str(document_id),
                details=details,
            )
        )
        db.commit()
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()
    return KGDeleteResponse(document_id=document_id, **(stats or {}))


@router.post(
    "/documents/{document_id}/extract", response_model=KGExtractResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
async def run_kg_extraction_for_document(
    document_id: UUID,
    response: Response,
    options: Annotated[KGExtractionOptions, Depends(kg_extraction_options)],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Trigger KG extraction for a processed document (rebuilds events/entities from chunks).
    """
    _ensure_enabled()
    document = _get_extraction_document(db, tenant_id=tenant_id, document_id=document_id, account_id=account_id)
    chunks = _document_chunks_for_extraction(db, tenant_id=tenant_id, document_id=document_id)
    effective = _effective_kg_extraction_options(document, options)
    chunks = _scope_chunks_to_pipeline(chunks, document_id=document_id, pipeline_hash=effective.pipeline_hash)

    # If async=true, enqueue KG extraction (default remains synchronous for compatibility).
    if bool(options.async_mode):
        return await _enqueue_kg_extraction_response(
            db=db,
            document=document,
            document_id=document_id,
            tenant_id=tenant_id,
            account_id=account_id,
            chunks=chunks,
            response=response,
            effective=effective,
        )

    events = await _run_sync_kg_extraction(
        chunks=chunks,
        tenant_id=tenant_id,
        account_id=account_id,
        effective=effective,
    )

    # Best-effort audit log: extraction completed (PII-minimal).
    _audit_kg_extraction(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document_id=document_id,
        action="kg.document.extract",
        details=_extraction_audit_details(
            async_mode=False,
            effective=effective,
            chunk_count=len(chunks),
            event_count=len(events or []),
        ),
    )

    return KGExtractResponse(
        document_id=document_id,
        chunk_count=len(chunks),
        event_count=len(events),
    )


@router.post("/search", response_model=KGSearchResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def run_kg_search(
    payload: KGSearchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Run KG search (query -> recall/expand/rerank) for the current tenant.
    """
    _ensure_enabled()

    if payload.tenant_id and payload.tenant_id != tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id mismatch")

    allowed_doc_ids: list[UUID] | None = None
    scope_dataset_id: UUID | None = None

    if payload.document_ids:
        allowed_doc_ids = _resolve_allowed_documents(
            document_ids=payload.document_ids,
            dataset_id=None,
            tenant_id=tenant_id,
            account_id=account_id,
            db=db,
        )
        if allowed_doc_ids is not None and not allowed_doc_ids:
            # Explicitly scoped to documents, but none are accessible after ACL filtering.
            return KGSearchResponse(
                result={
                    "events": [],
                    "entities": [],
                    "clues": [],
                    "stats": {"reason": "no_accessible_documents"},
                    "query": {"original": payload.query},
                },
                query=payload.query,
            )
    elif payload.dataset_id:
        # Enterprise semantics: allow dataset-scoped search without enumerating all document_ids.
        ds = DatasetService.get_dataset(db, tenant_id, payload.dataset_id)
        DatasetService.assert_dataset_readable(db, ds, account_id)
        scope_dataset_id = payload.dataset_id
    else:
        raise HTTPException(status_code=400, detail="dataset_id is required when document_ids is empty")

    try:
        result = await kg_search(
            query=payload.query,
            tenant_id=tenant_id,
            document_ids=allowed_doc_ids,
            dataset_id=scope_dataset_id,
            account_id=account_id,
        )
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise HTTPException(status_code=504, detail="KG search timed out") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"KG search failed: {exc}") from exc

    return KGSearchResponse(result=result, query=payload.query)
