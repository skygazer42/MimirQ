import asyncio
import contextlib
import gzip
import hashlib
import time
import uuid
import zlib
from datetime import UTC
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.core.errors import ConfigError
from app.rag.core.logging import get_logger
from app.rag.kg.pipeline import extract_events, kg_search
from app.rag.kg.schemas import (
    KGDeleteResponse,
    KGEntityAliasCreateRequest,
    KGEntityAliasesResponse,
    KGEntityAliasItem,
    KGEntityAliasSuggestionItem,
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
    KGPredicateOntologyCreateRequest,
    KGPredicateOntologyItem,
    KGPredicateOntologyListResponse,
    KGPredicateOntologyUpdateRequest,
    KGManualImportDeleteResponse,
    KGManualImportListResponse,
    KGManualImportPreviewResponse,
    KGManualImportRequest,
    KGManualImportResponse,
    KGSearchRequest,
    KGSearchResponse,
    KGStatsResponse,
)
from app.services.dataset_service import DatasetService
from app.services.document_access import filter_allowed_document_ids, list_accessible_document_ids
from app.services.metrics_logger import log_metrics

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger(__name__)

KG_ENTITY_NOT_FOUND_DETAIL = "KG entity not found"
PIPELINE_VERSION_FILTER_DESC = "Optional pipeline version filter (defaults to active pipeline per document)"
DATASET_SCOPE_FILTER_DESC = "Optional dataset scope resolved server-side to accessible documents"
INCLUDE_ENTITY_LINKS_DESC = "Include entity-entity co-occurrence links"
INCLUDE_RELATION_LINKS_DESC = "Include entity-entity relation links (triples)"
KG_API_GRAPH_METRIC = "kg.api.graph"
KG_API_GRAPH_EXPAND_METRIC = "kg.api.graph_expand"


def _log_kg_api_metric(event: str, **fields: object) -> None:
    if not bool(getattr(settings, "KG_API_METRICS_ENABLED", False)):
        return
    try:
        payload: dict[str, object] = {"event": event}
        payload.update({k: v for k, v in fields.items() if v is not None})
        log_metrics(payload)
    except Exception:
        # Best-effort only; metrics must never break the API.
        pass


def _stable_group_for(entity_type: str, *, buckets: int = 24) -> int:
    """Stable group id for frontend coloring (deterministic across requests)."""
    key = (entity_type or "unknown").strip().lower() or "unknown"
    buckets_i = max(1, int(buckets))
    digest = zlib.crc32(key.encode("utf-8"))
    return int(digest % buckets_i) + 1


def _ensure_enabled():
    if not settings.KG_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="KG is disabled. Set KG_ENABLED=true in your environment to enable it.",
        )


def _resolve_entity_id_via_redirects(
    *,
    db: Session,
    tenant_id: UUID,
    entity_id: UUID,
    max_hops: int = 8,
) -> UUID:
    """
    Resolve an entity id to its canonical id via kg_entity_redirects.

    This is used to keep URLs stable after merges and to avoid "ghost entities"
    leaking into the UI/API when entities have been merged.
    """
    from app.rag.kg.models import KgEntityRedirect

    cur = entity_id
    hops = 0
    while hops < max(1, int(max_hops or 0)):
        hops += 1
        q = db.query(KgEntityRedirect)
        # Compatibility: some unit tests use a lightweight FakeQuery that only implements `.filter(...)`.
        if hasattr(q, "filter_by"):
            q = q.filter_by(tenant_id=tenant_id, from_entity_id=cur)
        else:
            q = q.filter(KgEntityRedirect.tenant_id == tenant_id, KgEntityRedirect.from_entity_id == cur)
        row = q.first()
        if not row:
            break
        nxt = getattr(row, "to_entity_id", None)
        if nxt is None or nxt == cur:
            break
        cur = nxt
    return cur


def _relation_snapshot(rel: object) -> dict[str, Any]:
    """Best-effort serialize a KgRelation row into a JSON-safe dict for undo payloads."""
    return {
        "id": str(getattr(rel, "id", "")),
        "tenant_id": str(getattr(rel, "tenant_id", "")),
        "pipeline_hash": getattr(rel, "pipeline_hash", None),
        "document_id": str(getattr(rel, "document_id", "")) if getattr(rel, "document_id", None) else None,
        "chunk_id": str(getattr(rel, "chunk_id", "")) if getattr(rel, "chunk_id", None) else None,
        "event_id": str(getattr(rel, "event_id", "")) if getattr(rel, "event_id", None) else None,
        "subject_entity_id": str(getattr(rel, "subject_entity_id", "")),
        "predicate": getattr(rel, "predicate", None),
        "predicate_raw": getattr(rel, "predicate_raw", None),
        "object_entity_id": str(getattr(rel, "object_entity_id", "")),
        "confidence": float(getattr(rel, "confidence", 0.0) or 0.0),
        "qualifiers": getattr(rel, "qualifiers", None),
        "references": getattr(rel, "references", None),
        "extra_data": getattr(rel, "extra_data", None),
    }


def _event_entity_snapshot(assoc: object) -> dict[str, Any]:
    """Best-effort serialize a KgEventEntity row into a JSON-safe dict for undo payloads."""
    return {
        "id": str(getattr(assoc, "id", "")),
        "event_id": str(getattr(assoc, "event_id", "")),
        "entity_id": str(getattr(assoc, "entity_id", "")),
        "weight": float(getattr(assoc, "weight", 1.0) or 1.0),
        "role": getattr(assoc, "role", None),
        "extra_data": getattr(assoc, "extra_data", None),
    }


def _uuid_or_none(value: object) -> UUID | None:
    try:
        if value is None:
            return None
        return UUID(str(value))
    except Exception:
        return None


def _uuid_list(values: object) -> list[UUID]:
    if not isinstance(values, list):
        return []
    out: list[UUID] = []
    for v in values:
        u = _uuid_or_none(v)
        if u is not None:
            out.append(u)
    return out


def _dict_list(values: object) -> list[dict]:
    if not isinstance(values, list):
        return []
    out: list[dict] = []
    for v in values:
        if isinstance(v, dict):
            out.append(v)
    return out


def _audit_hash_text(text: str) -> str:
    """Stable short hash for potentially sensitive strings (PII-minimal)."""
    raw = (text or "").encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()[:16]


def _doc_pipeline_hash(meta: object) -> str | None:
    """
    Best-effort pipeline hash extraction from document metadata.

    We prefer active_pipeline_hash when present, falling back to pipeline_hash.
    """
    if not isinstance(meta, dict):
        return None
    ph = meta.get("active_pipeline_hash") or meta.get("pipeline_hash") or None
    s = str(ph or "").strip()
    return s or None


def _chunk_matches_pipeline(chunk: object, *, document_id: UUID, pipeline_hash: str) -> bool:
    """
    Best-effort check whether a chunk belongs to a specific pipeline version.

    This is used by KG extraction to avoid mixing chunk versions when a document
    has been re-processed under multiple pipelines.
    """
    meta_any = getattr(chunk, "doc_metadata", None)
    if not isinstance(meta_any, dict):
        return False
    doc_key = str(meta_any.get("doc_pipeline_key") or "").strip()
    if doc_key and doc_key == f"{document_id}:{pipeline_hash}":
        return True
    ph = _doc_pipeline_hash(meta_any)
    return bool(ph and ph == pipeline_hash)


def _active_pipeline_hash_expr(doc_model):  # noqa: ANN001
    """
    SQL expression for a document's active pipeline hash.

    Mirrors app.core.pipeline_versions.get_active_pipeline_hash semantics:
    - prefer metadata.active_pipeline_hash
    - fallback to metadata.pipeline_hash
    """
    from sqlalchemy import func  # noqa: WPS433

    return func.coalesce(
        doc_model.doc_metadata["active_pipeline_hash"].astext,  # type: ignore[attr-defined]
        doc_model.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
    )


def _apply_event_pipeline_scope(query, *, pipeline_hash: str | None):  # noqa: ANN001
    """
    Apply pipeline scoping to a query that includes KgSourceEvent.

    - pipeline_hash provided -> strict filter to that pipeline hash (diagnostics / A/B)
    - pipeline_hash None -> default to document.active_pipeline_hash (no cross-version mixing)
    """
    from sqlalchemy import and_  # noqa: WPS433

    from app.models.document import Document as DBDocument  # noqa: WPS433
    from app.rag.kg.models import KgSourceEvent  # noqa: WPS433

    if pipeline_hash:
        return query.filter(KgSourceEvent.pipeline_hash == str(pipeline_hash))

    return query.join(
        DBDocument,
        and_(
            DBDocument.id == KgSourceEvent.document_id,
            DBDocument.tenant_id == KgSourceEvent.tenant_id,
        ),
    ).filter(KgSourceEvent.pipeline_hash == _active_pipeline_hash_expr(DBDocument))


def _apply_relation_pipeline_scope(query, *, pipeline_hash: str | None):  # noqa: ANN001
    """
    Apply pipeline scoping to a query that includes KgRelation.

    Relations are versioned independently from events (but share the same pipeline_hash).
    """
    from sqlalchemy import and_  # noqa: WPS433

    from app.models.document import Document as DBDocument  # noqa: WPS433
    from app.rag.kg.models import KgRelation  # noqa: WPS433

    if pipeline_hash:
        return query.filter(KgRelation.pipeline_hash == str(pipeline_hash))

    return query.join(
        DBDocument,
        and_(
            DBDocument.id == KgRelation.document_id,
            DBDocument.tenant_id == KgRelation.tenant_id,
        ),
    ).filter(KgRelation.pipeline_hash == _active_pipeline_hash_expr(DBDocument))


def _resolve_allowed_documents(
    *,
    document_ids: list[UUID] | None,
    dataset_id: UUID | None,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> list[UUID]:
    eff_limit = max(0, int(getattr(settings, "KG_API_MAX_DOCUMENT_IDS", 500) or 500))
    if document_ids:
        # Deduplicate while preserving original order.
        seen: set[UUID] = set()
        deduped: list[UUID] = []
        for doc_id in document_ids:
            if doc_id not in seen:
                seen.add(doc_id)
                deduped.append(doc_id)

        if eff_limit > 0 and len(deduped) > eff_limit:
            raise HTTPException(status_code=400, detail=f"Too many document_ids (max {eff_limit})")

        return filter_allowed_document_ids(db, tenant_id, account_id, deduped)
    return list_accessible_document_ids(
        db,
        tenant_id,
        account_id,
        dataset_id=dataset_id,
        status="completed",
        limit=eff_limit,
    )


@router.get("/graph", response_model=KGGraphResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_kg_graph(
    document_ids: Annotated[list[UUID] | None, Query()] = None,
    dataset_id: Annotated[UUID | None, Query(description=DATASET_SCOPE_FILTER_DESC)] = None,
    pipeline_hash: Annotated[str | None, Query(
        min_length=1,
        max_length=200,
        description=PIPELINE_VERSION_FILTER_DESC,
    )] = None,
    max_events: Annotated[int, Query(ge=1, le=2000)] = 200,
    max_entities: Annotated[int, Query(ge=1, le=5000)] = 400,
    max_links: Annotated[int, Query(ge=1, le=20000)] = 2000,
    include_entity_links: Annotated[bool, Query(description=INCLUDE_ENTITY_LINKS_DESC)] = False,
    include_relation_links: Annotated[bool, Query(description=INCLUDE_RELATION_LINKS_DESC)] = False,
    min_shared_events: Annotated[int, Query(ge=1, le=100)] = 2,
    max_entity_links: Annotated[int, Query(ge=0, le=20000)] = 1000,
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

    allowed_doc_ids: list[UUID]
    allowed_doc_ids = _resolve_allowed_documents(
        document_ids=document_ids,
        dataset_id=dataset_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )

    if not allowed_doc_ids:
        out = KGGraphResponse(nodes=[], links=[], stats={"reason": "no_accessible_documents"})
        _log_kg_api_metric(
            KG_API_GRAPH_METRIC,
            tenant_id=str(tenant_id),
            docs=0,
            events=0,
            entities=0,
            links=0,
            elapsed_sec=round(float(time.perf_counter() - t0), 3),
        )
        return out

    from collections import Counter

    from sqlalchemy import func

    from app.rag.kg.models import KgEntity, KgEventEntity, KgRelation, KgSourceEvent
    from app.rag.kg.provenance import build_event_entity_provenance

    events_q = (
        db.query(KgSourceEvent)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
        )
    )
    events_q = _apply_event_pipeline_scope(events_q, pipeline_hash=pipeline_hash)
    events = events_q.order_by(KgSourceEvent.updated_at.desc()).limit(int(max_events)).all()

    if not events:
        out = KGGraphResponse(nodes=[], links=[], stats={"events": 0, "entities": 0, "links": 0})
        _log_kg_api_metric(
            KG_API_GRAPH_METRIC,
            tenant_id=str(tenant_id),
            docs=len(allowed_doc_ids),
            events=0,
            entities=0,
            links=0,
            elapsed_sec=round(float(time.perf_counter() - t0), 3),
        )
        return out

    event_ids = [e.id for e in events]

    # Compute event degrees across all edges (for node sizing).
    event_degree: Counter[str] = Counter()
    degree_rows = (
        db.query(KgEventEntity.event_id, func.count(KgEventEntity.entity_id).label("cnt"))
        .filter(KgEventEntity.event_id.in_(event_ids))
        .group_by(KgEventEntity.event_id)
        .all()
    )
    for ev_id, cnt in degree_rows:
        event_degree[str(ev_id)] = int(cnt or 0)

    # Prefilter entities in SQL to reduce join row volume.
    entity_hit_count: Counter[str] = Counter()
    ent_rows = (
        db.query(KgEventEntity.entity_id, func.count(KgEventEntity.event_id).label("cnt"))
        .filter(KgEventEntity.event_id.in_(event_ids))
        .group_by(KgEventEntity.entity_id)
        .order_by(func.count(KgEventEntity.event_id).desc())
        .limit(int(max_entities))
        .all()
    )
    allowed_entity_ids = [row[0] for row in ent_rows if row and row[0]]
    allowed_entity_id_strs = {str(eid) for eid in allowed_entity_ids}
    for ent_id, cnt in ent_rows:
        entity_hit_count[str(ent_id)] = int(cnt or 0)

    if not allowed_entity_ids:
        # Events exist but no entity links.
        nodes = []
        for ev in events:
            eid = str(ev.id)
            nodes.append(
                {
                    "id": eid,
                    "label": (ev.title or "").strip() or eid,
                    "group": 0,
                    "val": max(1, int(event_degree.get(eid, 0))),
                    "meta": {
                        "kind": "event",
                        "document_id": str(ev.document_id) if ev.document_id else "",
                        "chunk_id": str(ev.chunk_id) if ev.chunk_id else "",
                    },
                }
            )
        out = KGGraphResponse(nodes=nodes, links=[], stats={"events": len(events), "entities": 0, "links": 0})
        _log_kg_api_metric(
            KG_API_GRAPH_METRIC,
            tenant_id=str(tenant_id),
            docs=len(allowed_doc_ids),
            events=len(events),
            entities=0,
            links=0,
            elapsed_sec=round(float(time.perf_counter() - t0), 3),
        )
        return out

    # Fetch join rows only for the selected entity ids.
    rows = (
        db.query(KgEventEntity, KgEntity)
        .join(KgEntity, KgEntity.id == KgEventEntity.entity_id)
        .filter(
            KgEventEntity.event_id.in_(event_ids),
            KgEventEntity.entity_id.in_(allowed_entity_ids),
        )
        .all()
    )

    # Stable grouping for entity types (frontend coloring).

    nodes: list[dict] = []
    links: list[dict] = []

    # Event nodes
    for ev in events:
        eid = str(ev.id)
        nodes.append(
            {
                "id": eid,
                "label": (ev.title or "").strip() or eid,
                "group": 0,
                "val": max(1, int(event_degree.get(eid, 0))),
                "meta": {
                    "kind": "event",
                    "document_id": str(ev.document_id) if ev.document_id else "",
                    "chunk_id": str(ev.chunk_id) if ev.chunk_id else "",
                },
            }
        )

    # Entity nodes + links (capped)
    seen_entities: set[str] = set()
    for assoc, ent in rows:
        ent_id = str(ent.id)
        if ent_id not in allowed_entity_id_strs:
            continue

        if ent_id not in seen_entities:
            seen_entities.add(ent_id)
            nodes.append(
                {
                    "id": ent_id,
                    "label": (ent.name or "").strip() or ent_id,
                    "group": _stable_group_for(getattr(ent, "type", "") or "unknown"),
                    "val": max(1, int(entity_hit_count.get(ent_id, 0))),
                    "meta": {
                        "kind": "entity",
                        "type": getattr(ent, "type", None),
                        "normalized_name": getattr(ent, "normalized_name", None),
                    },
                }
            )

        if len(links) >= int(max_links):
            continue

        raw_extra = getattr(assoc, "extra_data", None)
        edge_meta = {"kind": "event_entity"}
        edge_meta.update(
            build_event_entity_provenance(
                document_id=(raw_extra.get("document_id") if isinstance(raw_extra, dict) else None),
                chunk_id=(raw_extra.get("chunk_id") if isinstance(raw_extra, dict) else None),
                references=(raw_extra if isinstance(raw_extra, dict) else None),
            )
        )
        links.append(
            {
                "source": str(assoc.event_id),
                "target": ent_id,
                "label": (assoc.role or "").strip() or getattr(ent, "type", "") or "mentions",
                "weight": float(getattr(assoc, "weight", 1.0) or 1.0),
                "meta": edge_meta,
            }
        )

    event_entity_links = len(links)

    relation_links_added = 0
    if bool(include_relation_links) and len(links) < int(max_links):
        remaining_budget = max(0, int(max_links) - len(links))
        if remaining_budget > 0:
            rel_q = (
                db.query(KgRelation)
                .filter(
                    KgRelation.tenant_id == tenant_id,
                    KgRelation.document_id.in_(allowed_doc_ids),
                    KgRelation.subject_entity_id.in_(allowed_entity_ids),
                    KgRelation.object_entity_id.in_(allowed_entity_ids),
                )
            )
            rel_q = _apply_relation_pipeline_scope(rel_q, pipeline_hash=pipeline_hash)
            rel_rows = rel_q.order_by(KgRelation.updated_at.desc()).limit(int(remaining_budget)).all()

            for rel in rel_rows:
                if len(links) >= int(max_links):
                    break
                subj = str(getattr(rel, "subject_entity_id", "") or "")
                obj = str(getattr(rel, "object_entity_id", "") or "")
                if not subj or not obj:
                    continue
                pred = str(getattr(rel, "predicate", "") or "").strip()
                if not pred:
                    continue
                conf_raw = getattr(rel, "confidence", None)
                try:
                    conf = float(conf_raw) if conf_raw is not None else 1.0
                except Exception:
                    conf = 1.0

                links.append(
                    {
                        "source": subj,
                        "target": obj,
                        "label": pred,
                        "weight": max(0.0, conf),
                        "meta": {
                            "kind": "entity_relation",
                            "predicate": pred,
                            "confidence": conf,
                            "document_id": str(getattr(rel, "document_id", "") or ""),
                            "chunk_id": str(getattr(rel, "chunk_id", "") or ""),
                            "event_id": str(getattr(rel, "event_id", "") or ""),
                        },
                    }
                )
                relation_links_added += 1

    entity_links_added = 0
    if bool(include_entity_links) and int(max_entity_links) > 0 and len(links) < int(max_links):
        from itertools import combinations

        per_event_entity_cap = int(getattr(settings, "KG_ENTITY_LINK_MAX_ENTITIES_PER_EVENT", 60) or 60)
        per_event_entity_cap = max(0, min(per_event_entity_cap, 500))

        event_to_entities: dict[str, set[str]] = {}
        for assoc, ent in rows:
            ent_id = str(ent.id)
            if ent_id not in allowed_entity_id_strs:
                continue
            event_to_entities.setdefault(str(assoc.event_id), set()).add(ent_id)

        co_counts: Counter[tuple[str, str]] = Counter()
        for ent_ids in event_to_entities.values():
            ids = sorted(ent_ids)
            if len(ids) < 2:
                continue
            if per_event_entity_cap > 0 and len(ids) > per_event_entity_cap:
                ids = ids[:per_event_entity_cap]
            for a, b in combinations(ids, 2):
                co_counts[(a, b)] += 1

        remaining_budget = max(0, int(max_links) - len(links))
        edge_limit = min(int(max_entity_links), remaining_budget)
        for (a, b), cnt in co_counts.most_common(edge_limit):
            if int(cnt) < int(min_shared_events):
                break
            if len(links) >= int(max_links):
                break
            links.append(
                {
                    "source": a,
                    "target": b,
                    "label": "co_occurs",
                    "weight": float(cnt),
                    "meta": {"kind": "entity_entity", "shared_events": int(cnt)},
                }
            )
            entity_links_added += 1

    out = KGGraphResponse(
        nodes=nodes,
        links=links,
        stats={
            "events": len(events),
            "entities": len(seen_entities),
            "links": min(len(links), int(max_links)),
            "event_entity_links": event_entity_links,
            "entity_relation_links": relation_links_added,
            "entity_entity_links": entity_links_added,
        },
    )
    _log_kg_api_metric(
        KG_API_GRAPH_METRIC,
        tenant_id=str(tenant_id),
        docs=len(allowed_doc_ids),
        events=int(out.stats.get("events", 0) or 0),
        entities=int(out.stats.get("entities", 0) or 0),
        links=int(out.stats.get("links", 0) or 0),
        elapsed_sec=round(float(time.perf_counter() - t0), 3),
    )
    return out


@router.get("/graph/expand", response_model=KGGraphResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def expand_kg_graph(
    node_id: Annotated[UUID, Query(description="Center node id (KgSourceEvent.id or KgEntity.id)")],
    document_ids: Annotated[list[UUID] | None, Query()] = None,
    dataset_id: Annotated[UUID | None, Query(description=DATASET_SCOPE_FILTER_DESC)] = None,
    pipeline_hash: Annotated[str | None, Query(
        min_length=1,
        max_length=200,
        description=PIPELINE_VERSION_FILTER_DESC,
    )] = None,
    max_events: Annotated[int, Query(ge=1, le=500)] = 50,
    max_entities: Annotated[int, Query(ge=1, le=5000)] = 400,
    max_links: Annotated[int, Query(ge=1, le=20000)] = 5000,
    include_entity_links: Annotated[bool, Query(description=INCLUDE_ENTITY_LINKS_DESC)] = False,
    include_relation_links: Annotated[bool, Query(description=INCLUDE_RELATION_LINKS_DESC)] = False,
    min_shared_events: Annotated[int, Query(ge=1, le=100)] = 2,
    max_entity_links: Annotated[int, Query(ge=0, le=20000)] = 2000,
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
        document_ids=document_ids,
        dataset_id=dataset_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    if not allowed_doc_ids:
        out = KGGraphResponse(nodes=[], links=[], stats={"reason": "no_accessible_documents"})
        _log_kg_api_metric(
            KG_API_GRAPH_EXPAND_METRIC,
            tenant_id=str(tenant_id),
            docs=0,
            events=0,
            entities=0,
            links=0,
            elapsed_sec=round(float(time.perf_counter() - t0), 3),
        )
        return out

    from collections import Counter

    from app.rag.kg.models import KgEntity, KgEventEntity, KgRelation, KgSourceEvent
    from app.rag.kg.provenance import build_event_entity_provenance

    # Determine node kind: event (scoped by allowed documents) or entity (tenant-scoped).
    center_event_q = (
        db.query(KgSourceEvent)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.id == node_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
        )
    )
    center_event_q = _apply_event_pipeline_scope(center_event_q, pipeline_hash=pipeline_hash)
    center_event = center_event_q.first()

    events: list[KgSourceEvent] = []

    if center_event:
        # Expand event -> entities -> other related events (by shared entities)
        entity_ids = (
            db.query(KgEventEntity.entity_id)
            .filter(KgEventEntity.event_id == center_event.id)
            .limit(2000)
            .all()
        )
        entity_ids_flat = [row[0] for row in entity_ids]

        related_event_ids: list[UUID] = []
        if entity_ids_flat and int(max_events) > 1:
            related_q = (
                db.query(KgEventEntity.event_id)
                .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
                .filter(
                    KgSourceEvent.tenant_id == tenant_id,
                    KgSourceEvent.document_id.in_(allowed_doc_ids),
                    KgEventEntity.entity_id.in_(entity_ids_flat),
                    KgEventEntity.event_id != center_event.id,
                )
            )
            related_q = _apply_event_pipeline_scope(related_q, pipeline_hash=pipeline_hash)
            related_event_ids = [
                row[0]
                for row in (
                    related_q.order_by(KgSourceEvent.updated_at.desc())
                    .limit(max(0, int(max_events) - 1))
                    .all()
                )
            ]

        event_ids = [center_event.id] + related_event_ids
        events_q = (
            db.query(KgSourceEvent)
            .filter(
                KgSourceEvent.tenant_id == tenant_id,
                KgSourceEvent.id.in_(event_ids),
                KgSourceEvent.document_id.in_(allowed_doc_ids),
            )
        )
        events_q = _apply_event_pipeline_scope(events_q, pipeline_hash=pipeline_hash)
        events = events_q.order_by(KgSourceEvent.updated_at.desc()).limit(int(max_events)).all()
    else:
        center_entity = (
            db.query(KgEntity)
            .filter(
                KgEntity.tenant_id == tenant_id,
                KgEntity.id == node_id,
            )
            .first()
        )
        if not center_entity:
            raise HTTPException(status_code=404, detail="KG node not found")

        ev_ids_q = (
            db.query(KgEventEntity.event_id)
            .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
            .filter(
                KgSourceEvent.tenant_id == tenant_id,
                KgSourceEvent.document_id.in_(allowed_doc_ids),
                KgEventEntity.entity_id == center_entity.id,
            )
        )
        ev_ids_q = _apply_event_pipeline_scope(ev_ids_q, pipeline_hash=pipeline_hash)
        event_ids = [row[0] for row in ev_ids_q.order_by(KgSourceEvent.updated_at.desc()).limit(int(max_events)).all()]
        if not event_ids:
            out = KGGraphResponse(nodes=[], links=[], stats={"reason": "no_related_events"})
            _log_kg_api_metric(
                KG_API_GRAPH_EXPAND_METRIC,
                tenant_id=str(tenant_id),
                docs=len(allowed_doc_ids),
                events=0,
                entities=0,
                links=0,
                elapsed_sec=round(float(time.perf_counter() - t0), 3),
            )
            return out

        events_q = (
            db.query(KgSourceEvent)
            .filter(
                KgSourceEvent.tenant_id == tenant_id,
                KgSourceEvent.id.in_(event_ids),
                KgSourceEvent.document_id.in_(allowed_doc_ids),
            )
        )
        events_q = _apply_event_pipeline_scope(events_q, pipeline_hash=pipeline_hash)
        events = events_q.order_by(KgSourceEvent.updated_at.desc()).limit(int(max_events)).all()

    if not events:
        out = KGGraphResponse(nodes=[], links=[], stats={"events": 0, "entities": 0, "links": 0})
        _log_kg_api_metric(
            KG_API_GRAPH_EXPAND_METRIC,
            tenant_id=str(tenant_id),
            docs=len(allowed_doc_ids),
            events=0,
            entities=0,
            links=0,
            elapsed_sec=round(float(time.perf_counter() - t0), 3),
        )
        return out

    from sqlalchemy import func

    event_ids = [e.id for e in events]

    # Compute event degrees across all edges (for node sizing).
    event_degree: Counter[str] = Counter()
    degree_rows = (
        db.query(KgEventEntity.event_id, func.count(KgEventEntity.entity_id).label("cnt"))
        .filter(KgEventEntity.event_id.in_(event_ids))
        .group_by(KgEventEntity.event_id)
        .all()
    )
    for ev_id, cnt in degree_rows:
        event_degree[str(ev_id)] = int(cnt or 0)

    # Prefilter entities in SQL to reduce join row volume.
    entity_hit_count: Counter[str] = Counter()
    ent_rows = (
        db.query(KgEventEntity.entity_id, func.count(KgEventEntity.event_id).label("cnt"))
        .filter(KgEventEntity.event_id.in_(event_ids))
        .group_by(KgEventEntity.entity_id)
        .order_by(func.count(KgEventEntity.event_id).desc())
        .limit(int(max_entities))
        .all()
    )
    allowed_entity_ids = [row[0] for row in ent_rows if row and row[0]]
    allowed_entity_id_strs = {str(eid) for eid in allowed_entity_ids}
    for ent_id, cnt in ent_rows:
        entity_hit_count[str(ent_id)] = int(cnt or 0)

    if not allowed_entity_ids:
        nodes = []
        for ev in events:
            ev_id = str(ev.id)
            nodes.append(
                {
                    "id": ev_id,
                    "label": (ev.title or "").strip() or ev_id,
                    "group": 0,
                    "val": max(1, int(event_degree.get(ev_id, 0))),
                    "meta": {
                        "kind": "event",
                        "document_id": str(ev.document_id) if ev.document_id else "",
                        "chunk_id": str(ev.chunk_id) if ev.chunk_id else "",
                        "center": str(ev.id) == str(node_id),
                    },
                }
            )
        out = KGGraphResponse(nodes=nodes, links=[], stats={"events": len(events), "entities": 0, "links": 0})
        _log_kg_api_metric(
            KG_API_GRAPH_EXPAND_METRIC,
            tenant_id=str(tenant_id),
            docs=len(allowed_doc_ids),
            events=len(events),
            entities=0,
            links=0,
            elapsed_sec=round(float(time.perf_counter() - t0), 3),
        )
        return out

    rows = (
        db.query(KgEventEntity, KgEntity)
        .join(KgEntity, KgEntity.id == KgEventEntity.entity_id)
        .filter(
            KgEventEntity.event_id.in_(event_ids),
            KgEventEntity.entity_id.in_(allowed_entity_ids),
        )
        .all()
    )

    # Stable grouping by entity type for frontend coloring.

    nodes: list[dict] = []
    links: list[dict] = []

    # Event nodes
    for ev in events:
        ev_id = str(ev.id)
        nodes.append(
            {
                "id": ev_id,
                "label": (ev.title or "").strip() or ev_id,
                "group": 0,
                "val": max(1, int(event_degree.get(ev_id, 0))),
                "meta": {
                    "kind": "event",
                    "document_id": str(ev.document_id) if ev.document_id else "",
                    "chunk_id": str(ev.chunk_id) if ev.chunk_id else "",
                    "center": str(ev.id) == str(node_id),
                },
            }
        )

    seen_entities: set[str] = set()
    for assoc, ent in rows:
        ent_id = str(ent.id)
        if ent_id not in allowed_entity_id_strs:
            continue

        if ent_id not in seen_entities:
            seen_entities.add(ent_id)
            nodes.append(
                {
                    "id": ent_id,
                    "label": (ent.name or "").strip() or ent_id,
                    "group": _stable_group_for(getattr(ent, "type", "") or "unknown"),
                    "val": max(1, int(entity_hit_count.get(ent_id, 0))),
                    "meta": {
                        "kind": "entity",
                        "type": getattr(ent, "type", None),
                        "normalized_name": getattr(ent, "normalized_name", None),
                        "center": str(ent.id) == str(node_id),
                    },
                }
            )

        if len(links) >= int(max_links):
            continue

        raw_extra = getattr(assoc, "extra_data", None)
        edge_meta = {"kind": "event_entity"}
        edge_meta.update(
            build_event_entity_provenance(
                document_id=(raw_extra.get("document_id") if isinstance(raw_extra, dict) else None),
                chunk_id=(raw_extra.get("chunk_id") if isinstance(raw_extra, dict) else None),
                references=(raw_extra if isinstance(raw_extra, dict) else None),
            )
        )
        links.append(
            {
                "source": str(assoc.event_id),
                "target": ent_id,
                "label": (assoc.role or "").strip() or getattr(ent, "type", "") or "mentions",
                "weight": float(getattr(assoc, "weight", 1.0) or 1.0),
                "meta": edge_meta,
            }
        )

    entity_links_added = 0
    relation_links_added = 0
    base_link_count = len(links)
    if bool(include_relation_links) and len(links) < int(max_links):
        remaining_budget = max(0, int(max_links) - len(links))
        if remaining_budget > 0:
            rel_q = (
                db.query(KgRelation)
                .filter(
                    KgRelation.tenant_id == tenant_id,
                    KgRelation.document_id.in_(allowed_doc_ids),
                    KgRelation.subject_entity_id.in_(allowed_entity_ids),
                    KgRelation.object_entity_id.in_(allowed_entity_ids),
                )
            )
            rel_q = _apply_relation_pipeline_scope(rel_q, pipeline_hash=pipeline_hash)
            rel_rows = rel_q.order_by(KgRelation.updated_at.desc()).limit(int(remaining_budget)).all()

            for rel in rel_rows:
                if len(links) >= int(max_links):
                    break
                subj = str(getattr(rel, "subject_entity_id", "") or "")
                obj = str(getattr(rel, "object_entity_id", "") or "")
                if not subj or not obj:
                    continue
                pred = str(getattr(rel, "predicate", "") or "").strip()
                if not pred:
                    continue
                conf_raw = getattr(rel, "confidence", None)
                try:
                    conf = float(conf_raw) if conf_raw is not None else 1.0
                except Exception:
                    conf = 1.0

                links.append(
                    {
                        "source": subj,
                        "target": obj,
                        "label": pred,
                        "weight": max(0.0, conf),
                        "meta": {
                            "kind": "entity_relation",
                            "predicate": pred,
                            "confidence": conf,
                            "document_id": str(getattr(rel, "document_id", "") or ""),
                            "chunk_id": str(getattr(rel, "chunk_id", "") or ""),
                            "event_id": str(getattr(rel, "event_id", "") or ""),
                        },
                    }
                )
                relation_links_added += 1

    if bool(include_entity_links) and int(max_entity_links) > 0 and len(links) < int(max_links):
        from itertools import combinations

        per_event_entity_cap = int(getattr(settings, "KG_ENTITY_LINK_MAX_ENTITIES_PER_EVENT", 60) or 60)
        per_event_entity_cap = max(0, min(per_event_entity_cap, 500))

        event_to_entities: dict[str, set[str]] = {}
        for assoc, ent in rows:
            ent_id = str(ent.id)
            if ent_id not in allowed_entity_id_strs:
                continue
            event_to_entities.setdefault(str(assoc.event_id), set()).add(ent_id)

        co_counts: Counter[tuple[str, str]] = Counter()
        for ent_ids in event_to_entities.values():
            ids = sorted(ent_ids)
            if len(ids) < 2:
                continue
            if per_event_entity_cap > 0 and len(ids) > per_event_entity_cap:
                ids = ids[:per_event_entity_cap]
            for a, b in combinations(ids, 2):
                co_counts[(a, b)] += 1

        remaining_budget = max(0, int(max_links) - len(links))
        edge_limit = min(int(max_entity_links), remaining_budget)
        for (a, b), cnt in co_counts.most_common(edge_limit):
            if int(cnt) < int(min_shared_events):
                break
            if len(links) >= int(max_links):
                break
            links.append(
                {
                    "source": a,
                    "target": b,
                    "label": "co_occurs",
                    "weight": float(cnt),
                    "meta": {"kind": "entity_entity", "shared_events": int(cnt)},
                }
            )
            entity_links_added += 1

    out = KGGraphResponse(
        nodes=nodes,
        links=links,
        stats={
            "center_node_id": str(node_id),
            "events": len(events),
            "entities": len(seen_entities),
            "links": min(len(links), int(max_links)),
            "event_entity_links": base_link_count,
            "entity_relation_links": relation_links_added,
            "entity_entity_links": entity_links_added,
        },
    )
    _log_kg_api_metric(
        KG_API_GRAPH_EXPAND_METRIC,
        tenant_id=str(tenant_id),
        docs=len(allowed_doc_ids),
        events=int(out.stats.get("events", 0) or 0),
        entities=int(out.stats.get("entities", 0) or 0),
        links=int(out.stats.get("links", 0) or 0),
        elapsed_sec=round(float(time.perf_counter() - t0), 3),
    )
    return out


@router.get("/graph/search", response_model=list[KGGraphNode], responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def search_kg_graph_nodes(
    q: Annotated[str, Query(min_length=1, max_length=200, description="Search query")],
    kind: Annotated[str, Query(description="entity | event | all")] = "all",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    document_ids: Annotated[list[UUID] | None, Query()] = None,
    dataset_id: Annotated[UUID | None, Query(description=DATASET_SCOPE_FILTER_DESC)] = None,
    pipeline_hash: Annotated[str | None, Query(
        min_length=1,
        max_length=200,
        description=PIPELINE_VERSION_FILTER_DESC,
    )] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Search KG nodes (entities/events) for UI autocomplete / quick jump.
    """
    _ensure_enabled()

    allowed_doc_ids = _resolve_allowed_documents(
        document_ids=document_ids,
        dataset_id=dataset_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )

    from sqlalchemy import func, or_

    from app.rag.kg.models import KgEntity, KgEventEntity, KgSourceEvent

    q_text = (q or "").strip()
    if not q_text:
        return []

    if not allowed_doc_ids:
        return []

    mode = (kind or "all").strip().lower()
    if mode not in {"all", "entity", "event"}:
        mode = "all"

    nodes: list[KGGraphNode] = []

    # Split on whitespace and use % join so "foo   bar" matches "foo ... bar".
    import re

    terms = [t for t in re.split(r"\s+", q_text) if t]
    pattern = "%" + "%".join(terms[:6]) + "%" if terms else f"%{q_text}%"

    if mode in {"all", "entity"}:
        ent_q = (
            db.query(KgEntity.id, func.max(KgEntity.updated_at).label("last_seen"))
            .join(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
            .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
            .filter(
                KgEntity.tenant_id == tenant_id,
                KgSourceEvent.tenant_id == tenant_id,
                KgSourceEvent.document_id.in_(allowed_doc_ids),
                or_(
                    KgEntity.name.ilike(pattern),
                    KgEntity.normalized_name.ilike(pattern),
                ),
            )
        )
        ent_q = _apply_event_pipeline_scope(ent_q, pipeline_hash=pipeline_hash)
        ent_rows = (
            ent_q.group_by(KgEntity.id)
            .order_by(func.max(KgEntity.updated_at).desc())
            .limit(int(limit))
            .all()
        )
        entity_ids = [row[0] for row in ent_rows if row and row[0]]
        if entity_ids:
            ents_by_id = {
                ent.id: ent
                for ent in db.query(KgEntity)
                .filter(KgEntity.tenant_id == tenant_id, KgEntity.id.in_(entity_ids))
                .all()
            }
        else:
            ents_by_id = {}
        for entity_id in entity_ids:
            ent = ents_by_id.get(entity_id)
            if ent is None:
                continue
            nodes.append(
                KGGraphNode(
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
            )

    remaining = int(limit) - len(nodes)
    if remaining <= 0 or not allowed_doc_ids:
        return nodes[: int(limit)]

    if mode in {"all", "event"}:
        events_q = (
            db.query(KgSourceEvent)
            .filter(
                KgSourceEvent.tenant_id == tenant_id,
                KgSourceEvent.document_id.in_(allowed_doc_ids),
                or_(
                    KgSourceEvent.title.ilike(pattern),
                    KgSourceEvent.summary.ilike(pattern),
                ),
            )
        )
        events_q = _apply_event_pipeline_scope(events_q, pipeline_hash=pipeline_hash)
        events = events_q.order_by(KgSourceEvent.updated_at.desc()).limit(remaining).all()
        for ev in events:
            nodes.append(
                KGGraphNode(
                    id=str(ev.id),
                    label=(ev.title or "").strip() or str(ev.id),
                    group=0,
                    val=1,
                    meta={
                        "kind": "event",
                        "document_id": str(ev.document_id) if ev.document_id else "",
                        "chunk_id": str(ev.chunk_id) if ev.chunk_id else "",
                    },
                )
            )

    return nodes[: int(limit)]


@router.get("/stats", response_model=KGStatsResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_kg_stats(
    document_ids: Annotated[list[UUID] | None, Query()] = None,
    dataset_id: Annotated[UUID | None, Query(description=DATASET_SCOPE_FILTER_DESC)] = None,
    pipeline_hash: Annotated[str | None, Query(
        min_length=1,
        max_length=200,
        description=PIPELINE_VERSION_FILTER_DESC,
    )] = None,
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


@router.post("/imports/preview", response_model=KGManualImportPreviewResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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


@router.delete("/imports/{import_id}", response_model=KGManualImportDeleteResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def delete_manual_kg_import(
    import_id: str,
    prune_entities: Annotated[bool, Query(description="Delete entities created only by this import when they become orphaned")] = True,
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

    if not allowed_doc_ids:
        return {
            "schema": KG_SNAPSHOT_SCHEMA_V2 if include_details else KG_SNAPSHOT_SCHEMA_V1,
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

    from sqlalchemy import func

    from app.rag.kg.models import KgEntity, KgEventEntity, KgRelation, KgSourceEvent

    docs_count = (
        db.query(func.count(func.distinct(KgSourceEvent.document_id)))
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
            KgSourceEvent.pipeline_hash == pipeline_hash,
        )
        .scalar()
        or 0
    )
    event_count = (
        db.query(func.count(KgSourceEvent.id))
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
            KgSourceEvent.pipeline_hash == pipeline_hash,
        )
        .scalar()
        or 0
    )
    link_count = (
        db.query(func.count(KgEventEntity.id))
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
            KgSourceEvent.pipeline_hash == pipeline_hash,
        )
        .scalar()
        or 0
    )
    entity_count = (
        db.query(func.count(func.distinct(KgEventEntity.entity_id)))
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
            KgSourceEvent.pipeline_hash == pipeline_hash,
        )
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
    updated_at = (
        db.query(func.max(KgSourceEvent.updated_at))
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
            KgSourceEvent.pipeline_hash == pipeline_hash,
        )
        .scalar()
    )

    type_rows = (
        db.query(KgEntity.type, func.count(func.distinct(KgEntity.id)).label("cnt"))
        .join(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
            KgSourceEvent.pipeline_hash == pipeline_hash,
        )
        .group_by(KgEntity.type)
        .order_by(func.count(func.distinct(KgEntity.id)).desc(), KgEntity.type.asc())
        .limit(50)
        .all()
    )

    snapshot: dict[str, Any] = {
        "schema": KG_SNAPSHOT_SCHEMA_V2 if include_details else KG_SNAPSHOT_SCHEMA_V1,
        "pipeline_hash": str(pipeline_hash),
        "docs": int(docs_count),
        "events": int(event_count),
        "entities": int(entity_count),
        "links": int(link_count),
        "relations": int(relation_count),
        "entity_types": [{"type": str(t or "unknown"), "count": int(cnt or 0)} for (t, cnt) in type_rows],
        "updated_at": updated_at,
        "elapsed_sec": round(float(time.perf_counter() - t0), 3),
    }
    if not include_details:
        return snapshot

    event_rows = (
        db.query(KgSourceEvent)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
            KgSourceEvent.pipeline_hash == pipeline_hash,
        )
        .order_by(KgSourceEvent.updated_at.desc(), KgSourceEvent.id.asc())
        .limit(int(detail_limit))
        .all()
    )
    entity_rows = (
        db.query(KgEntity)
        .join(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
            KgSourceEvent.pipeline_hash == pipeline_hash,
        )
        .group_by(KgEntity.id)
        .order_by(KgEntity.type.asc(), KgEntity.name.asc(), KgEntity.id.asc())
        .limit(int(detail_limit))
        .all()
    )
    link_rows = (
        db.query(KgEventEntity)
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
            KgSourceEvent.pipeline_hash == pipeline_hash,
        )
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

    nodes: list[dict[str, Any]] = []
    for event in event_rows:
        props = {
            "title": event.title,
            "summary": event.summary,
            "document_id": str(event.document_id) if event.document_id else None,
            "chunk_id": str(event.chunk_id) if event.chunk_id else None,
            "extra_data": event.extra_data or {},
        }
        nodes.append(
            {
                "id": f"event:{event.id}",
                "kind": "event",
                "type": "event",
                "name": event.title,
                "props_hash": canonical_json_hash(props),
            }
        )
    for entity in entity_rows:
        props = {
            "name": entity.name,
            "type": entity.type,
            "description": entity.description,
            "normalized_name": entity.normalized_name,
            "extra_data": entity.extra_data or {},
        }
        nodes.append(
            {
                "id": f"entity:{entity.id}",
                "kind": "entity",
                "type": str(entity.type or "unknown"),
                "name": entity.name,
                "props_hash": canonical_json_hash(props),
            }
        )

    edges: list[dict[str, Any]] = []
    for link in link_rows:
        props = {
            "role": link.role,
            "weight": str(link.weight),
            "extra_data": link.extra_data or {},
        }
        edges.append(
            {
                "id": f"event_entity:{link.id}",
                "src": f"event:{link.event_id}",
                "dst": f"entity:{link.entity_id}",
                "kind": "event_entity",
                "predicate": str(link.role or "mentions"),
                "props_hash": canonical_json_hash(props),
            }
        )
    for relation in relation_rows:
        props = {
            "predicate": relation.predicate,
            "predicate_raw": relation.predicate_raw,
            "confidence": str(relation.confidence),
            "qualifiers": relation.qualifiers or {},
            "references": relation.references or {},
            "extra_data": relation.extra_data or {},
        }
        edges.append(
            {
                "id": f"relation:{relation.id}",
                "src": f"entity:{relation.subject_entity_id}",
                "dst": f"entity:{relation.object_entity_id}",
                "kind": "relation",
                "predicate": relation.predicate,
                "props_hash": canonical_json_hash(props),
            }
        )

    snapshot["nodes"] = nodes
    snapshot["edges"] = edges
    snapshot["detail_limits"] = {"nodes": int(detail_limit), "edges": int(detail_limit)}
    snapshot["detail_truncated"] = {
        "events": int(event_count) > len(event_rows),
        "entities": int(entity_count) > len(entity_rows),
        "links": int(link_count) > len(link_rows),
        "relations": int(relation_count) > len(relation_rows),
    }
    return snapshot


@router.post("/snapshots/diff", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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


@router.get("/graph/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_kg_graph(
    document_ids: Annotated[list[UUID] | None, Query()] = None,
    dataset_id: Annotated[UUID | None, Query(description=DATASET_SCOPE_FILTER_DESC)] = None,
    pipeline_hash: Annotated[str | None, Query(
        min_length=1,
        max_length=200,
        description=PIPELINE_VERSION_FILTER_DESC,
    )] = None,
    max_events: Annotated[int, Query(ge=1, le=2000)] = 200,
    max_entities: Annotated[int, Query(ge=1, le=5000)] = 400,
    max_links: Annotated[int, Query(ge=1, le=20000)] = 2000,
    include_entity_links: Annotated[bool, Query(description=INCLUDE_ENTITY_LINKS_DESC)] = False,
    include_relation_links: Annotated[bool, Query(description=INCLUDE_RELATION_LINKS_DESC)] = False,
    min_shared_events: Annotated[int, Query(ge=1, le=100)] = 2,
    max_entity_links: Annotated[int, Query(ge=0, le=20000)] = 1000,
    download: Annotated[bool, Query()] = True,
    gzip_output: Annotated[bool, Query(alias="gzip", description="Return gzipped GraphML")] = False,
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
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )

    import xml.etree.ElementTree as ET

    graphml_xmlns = "http" + "://graphml.graphdrawing.org/xmlns"
    root = ET.Element("graphml", xmlns=graphml_xmlns)

    def _key(*, key_id: str, kind: str, name: str, typ: str) -> None:
        ET.SubElement(
            root,
            "key",
            {
                "id": key_id,
                "for": kind,
                "attr.name": name,
                "attr.type": typ,
            },
        )

    _key(key_id="d0", kind="node", name="label", typ="string")
    _key(key_id="d1", kind="node", name="kind", typ="string")
    _key(key_id="d2", kind="node", name="type", typ="string")
    _key(key_id="d3", kind="node", name="normalized_name", typ="string")
    _key(key_id="d4", kind="node", name="document_id", typ="string")
    _key(key_id="d5", kind="node", name="chunk_id", typ="string")
    _key(key_id="d6", kind="node", name="group", typ="int")
    _key(key_id="d7", kind="node", name="val", typ="int")
    _key(key_id="e0", kind="edge", name="label", typ="string")
    _key(key_id="e1", kind="edge", name="weight", typ="double")
    _key(key_id="e2", kind="edge", name="kind", typ="string")
    _key(key_id="e3", kind="edge", name="shared_events", typ="int")

    graph_el = ET.SubElement(root, "graph", {"id": "G", "edgedefault": "directed"})

    for node in graph.nodes:
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

    for idx, link in enumerate(graph.links):
        e = ET.SubElement(
            graph_el,
            "edge",
            {
                "id": f"e{idx}",
                "source": str(link.source),
                "target": str(link.target),
            },
        )
        meta = dict(getattr(link, "meta", {}) or {})
        ET.SubElement(e, "data", {"key": "e0"}).text = str(getattr(link, "label", "") or "")
        ET.SubElement(e, "data", {"key": "e1"}).text = str(float(getattr(link, "weight", 1.0) or 1.0))
        ET.SubElement(e, "data", {"key": "e2"}).text = str(meta.get("kind") or "")
        ET.SubElement(e, "data", {"key": "e3"}).text = str(int(meta.get("shared_events") or 0))

    xml_text = ET.tostring(root, encoding="unicode")
    payload = f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_text}\n'

    headers = {}
    if download:
        ext = "graphml.gz" if gzip_output else "graphml"
        headers["Content-Disposition"] = f'attachment; filename="mimirq-kg-{tenant_id}.{ext}"'

    media_type = "application/graphml+xml"
    content: str | bytes = payload
    if gzip_output:
        headers["Content-Encoding"] = "gzip"
        content = gzip.compress(payload.encode("utf-8"), compresslevel=6)

    export_stats = dict(getattr(graph, "stats", {}) or {})
    _log_kg_api_metric(
        "kg.api.graph_export",
        tenant_id=str(tenant_id),
        docs_requested=(len(document_ids) if document_ids is not None else None),
        events=int(export_stats.get("events", 0) or 0),
        entities=int(export_stats.get("entities", 0) or 0),
        links=int(export_stats.get("links", 0) or 0),
        gzip=bool(gzip_output),
        bytes=len(content) if isinstance(content, (bytes, bytearray)) else len(content.encode("utf-8")),
        elapsed_sec=round(float(time.perf_counter() - t0), 3),
    )

    return Response(content=content, media_type=media_type, headers=headers)


@router.get("/events/{event_id}", response_model=KGEventDetailResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_kg_event_detail(
    event_id: UUID,
    document_ids: Annotated[list[UUID] | None, Query()] = None,
    dataset_id: Annotated[UUID | None, Query(description=DATASET_SCOPE_FILTER_DESC)] = None,
    pipeline_hash: Annotated[str | None, Query(
        min_length=1,
        max_length=200,
        description=PIPELINE_VERSION_FILTER_DESC,
    )] = None,
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

    ev_q = (
        db.query(KgSourceEvent)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.id == event_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
        )
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
                    else (getattr(ev, "references", None) if isinstance(getattr(ev, "references", None), dict) else None)
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
    pipeline_hash: Annotated[str | None, Query(
        min_length=1,
        max_length=200,
        description=PIPELINE_VERSION_FILTER_DESC,
    )] = None,
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


@router.get("/entities/{entity_id}/aliases", response_model=KGEntityAliasesResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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


@router.post("/entities/{entity_id}/aliases", response_model=KGEntityAliasItem, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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
        logger.debug("Ignoring non-critical KG API fallback failure: %s", exc)

    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug("Ignoring non-critical KG API fallback failure: %s", exc)
        raise

    return KGEntityAliasItem.model_validate(alias_row)


@router.delete("/entities/{entity_id}/aliases/{alias_id}", response_model=KGEntityAliasesResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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
        logger.debug("Ignoring non-critical KG API fallback failure: %s", exc)

    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug("Ignoring non-critical KG API fallback failure: %s", exc)
        raise

    # Return the current alias set after deletion.
    return list_kg_entity_aliases(entity_id=entity_id, tenant_id=tenant_id, account_id=account_id, db=db)


@router.get("/entities/{entity_id}/alias_suggestions", response_model=KGEntityAliasSuggestionsResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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

    from difflib import SequenceMatcher

    from sqlalchemy import and_  # noqa: WPS433

    from app.rag.kg.models import KgEntity

    resolved_id = _resolve_entity_id_via_redirects(db=db, tenant_id=tenant_id, entity_id=entity_id)
    ent = db.query(KgEntity).filter_by(tenant_id=tenant_id, id=resolved_id).first()
    if not ent:
        raise HTTPException(status_code=404, detail=KG_ENTITY_NOT_FOUND_DETAIL)

    eff_mode = (mode or "offline").strip().lower()
    want_k = int(k)

    # Offline deterministic: prefix + string similarity on normalized_name.
    norm = str(getattr(ent, "normalized_name", "") or "").strip()
    prefix = norm[:4] if len(norm) >= 4 else norm

    suggestions: list[KGEntityAliasSuggestionItem] = []
    if eff_mode == "offline" or not bool(getattr(ent, "vector", None)):
        q = db.query(KgEntity).filter(
            and_(
                KgEntity.tenant_id == tenant_id,
                KgEntity.type == getattr(ent, "type", None),
                KgEntity.id != resolved_id,
            )
        )
        if prefix:
            q = q.filter(KgEntity.normalized_name.like(f"{prefix}%"))  # noqa: WPS323
        candidates = q.order_by(KgEntity.normalized_name.asc(), KgEntity.id.asc()).limit(500).all()

        scored: list[tuple[float, str, KgEntity]] = []
        for c in candidates:
            c_norm = str(getattr(c, "normalized_name", "") or "").strip()
            if not c_norm:
                continue
            sim = float(SequenceMatcher(a=norm, b=c_norm).ratio())
            if sim < float(min_similarity):
                continue
            scored.append((sim, str(c.id), c))

        scored.sort(key=lambda t: (-t[0], t[1]))
        for sim, _sid, c in scored[:want_k]:
            suggestions.append(
                KGEntityAliasSuggestionItem(
                    entity_id=c.id,
                    name=str(getattr(c, "name", "") or ""),
                    type=str(getattr(c, "type", "") or "unknown"),
                    similarity=float(sim),
                    reason="offline:normalized_name_sequence_match",
                )
            )

        return KGEntityAliasSuggestionsResponse(
            entity_id=resolved_id,
            suggestions=suggestions,
            mode="offline",
            stats={"candidates": len(candidates), "returned": len(suggestions), "prefix": prefix},
        )

    # Vector mode (best-effort): use KG entity vectors if configured and available.
    try:
        from app.rag.kg.repository import EntityRepository  # noqa: WPS433

        repo = EntityRepository(db)
        hits = repo.search_similar(
            query_vector=list(ent.vector),
            tenant_id=tenant_id,
            k=max(1, int(want_k)),
            entity_type=str(getattr(ent, "type", "") or None) or None,
        )
        for h in hits:
            eid = _uuid_or_none(h.get("entity_id") or h.get("id"))
            if eid is None or eid == resolved_id:
                continue
            suggestions.append(
                KGEntityAliasSuggestionItem(
                    entity_id=eid,
                    name=str(h.get("name") or ""),
                    type=str(h.get("type") or "unknown"),
                    similarity=float(h.get("similarity", 0.0) or 0.0),
                    reason="vector:milvus_similarity",
                )
            )
        suggestions = suggestions[:want_k]
        return KGEntityAliasSuggestionsResponse(
            entity_id=resolved_id,
            suggestions=suggestions,
            mode="vector",
            stats={"returned": len(suggestions)},
        )
    except Exception:
        return KGEntityAliasSuggestionsResponse(
            entity_id=resolved_id,
            suggestions=[],
            mode="vector",
            stats={"returned": 0, "reason": "vector_mode_failed"},
        )


@router.post("/entities/merge/preview", response_model=KGEntityMergePreviewResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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


@router.get("/ontology/predicates", response_model=KGPredicateOntologyListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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


@router.post("/ontology/predicates", response_model=KGPredicateOntologyItem, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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
        logger.debug("Ignoring non-critical KG API fallback failure: %s", exc)

    try:
        db.commit()
        db.refresh(row)
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug("Ignoring non-critical KG API fallback failure: %s", exc)
        raise

    return KGPredicateOntologyItem.model_validate(row)


@router.patch("/ontology/predicates/{predicate_id}", response_model=KGPredicateOntologyItem, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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
        logger.debug("Ignoring non-critical KG API fallback failure: %s", exc)

    try:
        db.commit()
        db.refresh(row)
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug("Ignoring non-critical KG API fallback failure: %s", exc)
        raise

    return KGPredicateOntologyItem.model_validate(row)


@router.delete("/ontology/predicates/{predicate_id}", response_model=KGPredicateOntologyListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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
        logger.debug("Ignoring non-critical KG API fallback failure: %s", exc)

    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug("Ignoring non-critical KG API fallback failure: %s", exc)
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

    from datetime import datetime

    from app.models.audit_log import AuditLog
    from app.rag.kg.models import (
        KgEntity,
        KgEntityRedirect,
        KgEntityResolutionAction,
        KgEventEntity,
        KgRelation,
    )
    # Milvus is an optional side effect for entity resolution (controlled by settings);
    # keep imports lazy so unit tests don't require a running Milvus.

    source_raw = payload.source_entity_id
    target_raw = payload.target_entity_id
    if source_raw == target_raw:
        raise HTTPException(status_code=400, detail="source_entity_id must differ from target_entity_id")

    # Resolve through redirects so callers can merge via historical ids safely.
    source_id = _resolve_entity_id_via_redirects(db=db, tenant_id=tenant_id, entity_id=source_raw)
    target_id = _resolve_entity_id_via_redirects(db=db, tenant_id=tenant_id, entity_id=target_raw)
    if source_id == target_id:
        raise HTTPException(status_code=400, detail="Entities already resolve to the same canonical id")

    source_ent = db.query(KgEntity).filter_by(tenant_id=tenant_id, id=source_id).first()
    target_ent = db.query(KgEntity).filter_by(tenant_id=tenant_id, id=target_id).first()
    if not source_ent or not target_ent:
        raise HTTPException(status_code=404, detail=KG_ENTITY_NOT_FOUND_DETAIL)

    # Safety rail: merges across types are almost always incorrect.
    if str(getattr(source_ent, "type", "") or "").strip() != str(getattr(target_ent, "type", "") or "").strip():
        raise HTTPException(status_code=400, detail="Cannot merge entities of different types")

    # Gather affected rows (Python-level snapshots so unit tests don't require a DB).
    source_assocs = db.query(KgEventEntity).filter_by(entity_id=source_id).all()
    source_assoc_ids = {str(getattr(a, "id", "")) for a in source_assocs if getattr(a, "id", None)}
    assoc_snapshot_by_id: dict[str, dict[str, Any]] = {
        str(a.id): _event_entity_snapshot(a) for a in source_assocs if getattr(a, "id", None)
    }
    impacted_event_ids = {getattr(a, "event_id", None) for a in source_assocs if getattr(a, "event_id", None) is not None}

    # Relations: fetch both directions and dedupe by id.
    rel_rows = []
    rel_rows.extend(db.query(KgRelation).filter_by(tenant_id=tenant_id, subject_entity_id=source_id).all())
    rel_rows.extend(db.query(KgRelation).filter_by(tenant_id=tenant_id, object_entity_id=source_id).all())
    rel_by_id: dict[str, object] = {}
    for r in rel_rows:
        rid = str(getattr(r, "id", "") or "")
        if rid:
            rel_by_id[rid] = r
    source_relations = list(rel_by_id.values())
    source_relation_ids = {str(getattr(r, "id", "")) for r in source_relations if getattr(r, "id", None)}
    relation_snapshot_by_id: dict[str, dict[str, Any]] = {
        str(r.id): _relation_snapshot(r) for r in source_relations if getattr(r, "id", None)
    }

    # Create action row first so we can reference it from redirects.
    action = KgEntityResolutionAction(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        actor_id=str(account_id or "").strip() or None,
        action_type="merge",
        status="applied",
        payload={
            "version": 1,
            "action": "merge",
            "source_entity_id": str(source_id),
            "target_entity_id": str(target_id),
            "event_entity_updated_ids": sorted([sid for sid in source_assoc_ids if sid]),
            "relation_updated_ids": sorted([sid for sid in source_relation_ids if sid]),
            "event_entity_deleted_rows": [],
            "relation_deleted_rows": [],
            "redirect_created": False,
            "vector_deleted": False,
        },
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(action)

    # Audit log (lightweight, PII-minimal).
    try:
        db.add(
            AuditLog(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                actor_id=str(account_id or "").strip() or None,
                action="kg.entity.merge",
                resource_type="kg_entity",
                resource_id=str(target_id),
                details={
                    "source_entity_id": str(source_id),
                    "target_entity_id": str(target_id),
                },
            )
        )
    except Exception:
        # Best-effort only.
        pass

    # Redirect: only create if absent.
    redirect_created = False
    existing_redirect = db.query(KgEntityRedirect).filter_by(tenant_id=tenant_id, from_entity_id=source_id).first()
    if existing_redirect:
        if getattr(existing_redirect, "to_entity_id", None) != target_id:
            raise HTTPException(status_code=409, detail="Entity redirect already exists to a different canonical id")
    else:
        db.add(
            KgEntityRedirect(
                from_entity_id=source_id,
                tenant_id=tenant_id,
                to_entity_id=target_id,
                action_id=action.id,
                created_by=str(account_id or "").strip() or None,
                extra_data={"reason": "merge"},
                created_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        redirect_created = True

    # Apply association updates.
    for assoc in source_assocs:
        assoc.entity_id = target_id

    # Apply relation updates + remove self-relations introduced by the merge.
    relation_deleted_rows: list[dict[str, Any]] = []
    for rel in source_relations:
        rid = str(getattr(rel, "id", "") or "")
        if getattr(rel, "subject_entity_id", None) == source_id:
            rel.subject_entity_id = target_id
        if getattr(rel, "object_entity_id", None) == source_id:
            rel.object_entity_id = target_id

        if getattr(rel, "subject_entity_id", None) == getattr(rel, "object_entity_id", None):
            if rid and rid in relation_snapshot_by_id:
                relation_deleted_rows.append(relation_snapshot_by_id[rid])
            db.delete(rel)

    # Deduplicate event-entity edges created by the merge.
    deleted_assoc_rows: list[dict[str, Any]] = []
    if impacted_event_ids:
        current_target_assocs = db.query(KgEventEntity).filter_by(entity_id=target_id).all()
        by_event: dict[UUID, list[object]] = {}
        for a in current_target_assocs:
            ev_id = getattr(a, "event_id", None)
            if ev_id is None or ev_id not in impacted_event_ids:
                continue
            by_event.setdefault(ev_id, []).append(a)

        for _ev_id, rows in by_event.items():
            if len(rows) <= 1:
                continue
            # Prefer keeping the pre-existing target edge (id not in the updated source set).
            keep = None
            for r in rows:
                rid = str(getattr(r, "id", "") or "")
                if rid and rid not in source_assoc_ids:
                    keep = r
                    break
            if keep is None:
                keep = rows[0]

            keep_weight = float(getattr(keep, "weight", 1.0) or 1.0)
            keep_role = getattr(keep, "role", None)
            keep_extra = getattr(keep, "extra_data", None)

            for r in rows:
                if r is keep:
                    continue
                rid = str(getattr(r, "id", "") or "")
                w = float(getattr(r, "weight", 1.0) or 1.0)
                keep_weight = max(keep_weight, w)
                if not keep_role:
                    keep_role = getattr(r, "role", None)
                if not keep_extra:
                    keep_extra = getattr(r, "extra_data", None)

                # Only delete rows introduced by the merge (source edges). Keep original target edges.
                if rid and rid in source_assoc_ids:
                    snap = assoc_snapshot_by_id.get(rid) or _event_entity_snapshot(r)
                    # Ensure undo restores to the source entity.
                    snap["entity_id"] = str(source_id)
                    deleted_assoc_rows.append(snap)
                    db.delete(r)

            keep.weight = keep_weight
            keep.role = keep_role
            keep.extra_data = keep_extra

    # Best-effort: delete source entity vectors so vector recall doesn't return deprecated ids.
    vector_deleted = False
    if bool(getattr(settings, "KG_ENTITY_RESOLUTION_UPDATE_VECTORS_ENABLED", False)):
        try:
            from app.storage.vector.milvus import get_milvus_adapter, resolve_collection_name  # noqa: WPS433

            collection = resolve_collection_name("kg_entities")
            milvus = get_milvus_adapter(collection_name=collection, vector_field="embedding")
            milvus.delete([str(source_id)])
            vector_deleted = True
        except Exception:
            vector_deleted = False

    # Update the action payload with side effects so undo can restore state.
    payload_dict = dict(action.payload or {})
    payload_dict["event_entity_deleted_rows"] = deleted_assoc_rows
    payload_dict["relation_deleted_rows"] = relation_deleted_rows
    payload_dict["redirect_created"] = bool(redirect_created)
    payload_dict["vector_deleted"] = bool(vector_deleted)
    action.payload = payload_dict

    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug("Ignoring non-critical KG API fallback failure: %s", exc)
        raise

    return KGEntityMergeResponse(
        action_id=action.id,
        source_entity_id=source_id,
        target_entity_id=target_id,
        stats={
            "source_event_entity_edges": len(source_assocs),
            "source_relations": len(source_relations),
            "dedup_deleted_event_entity_edges": len(deleted_assoc_rows),
            "deleted_relations": len(relation_deleted_rows),
            "redirect_created": bool(redirect_created),
            "vector_deleted": bool(vector_deleted),
        },
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

    from datetime import datetime

    from app.models.audit_log import AuditLog
    from app.rag.kg.extraction.parser import EntityValueParser
    from app.rag.kg.models import KgEntity, KgEntityResolutionAction, KgEventEntity, KgRelation

    original_raw = payload.entity_id
    original_id = _resolve_entity_id_via_redirects(db=db, tenant_id=tenant_id, entity_id=original_raw)

    ent = db.query(KgEntity).filter_by(tenant_id=tenant_id, id=original_id).first()
    if not ent:
        raise HTTPException(status_code=404, detail=KG_ENTITY_NOT_FOUND_DETAIL)

    event_ids = [eid for eid in (payload.event_ids or []) if eid is not None]
    # Safety rail: require explicit scope and cap size.
    if not event_ids:
        raise HTTPException(status_code=400, detail="event_ids is required for split")
    if len(event_ids) > 5000:
        raise HTTPException(status_code=400, detail="Too many event_ids (max 5000)")
    event_id_set = set(event_ids)

    new_name = str(payload.new_entity_name or "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="new_entity_name is required")

    parser = EntityValueParser()
    new_norm = parser.normalize_name(new_name)

    new_entity_id = uuid.uuid4()
    new_ent = KgEntity(
        id=new_entity_id,
        tenant_id=tenant_id,
        name=new_name,
        type=str(getattr(ent, "type", "") or "unknown"),
        normalized_name=new_norm,
        description=None,
        vector=None,
        extra_data={"split_from": str(original_id)},
        created_at=datetime.now(UTC).replace(tzinfo=None),
        updated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(new_ent)

    moved_assoc_ids: list[str] = []
    source_assocs = db.query(KgEventEntity).filter_by(entity_id=original_id).all()
    for assoc in source_assocs:
        ev_id = getattr(assoc, "event_id", None)
        if ev_id is None or ev_id not in event_id_set:
            continue
        moved_assoc_ids.append(str(getattr(assoc, "id", "") or ""))
        assoc.entity_id = new_entity_id

    moved_relation_ids: list[str] = []
    rel_rows = []
    rel_rows.extend(db.query(KgRelation).filter_by(tenant_id=tenant_id, subject_entity_id=original_id).all())
    rel_rows.extend(db.query(KgRelation).filter_by(tenant_id=tenant_id, object_entity_id=original_id).all())
    rel_by_id: dict[str, object] = {}
    for r in rel_rows:
        rid = str(getattr(r, "id", "") or "")
        if rid:
            rel_by_id[rid] = r
    for rel in rel_by_id.values():
        ev_id = getattr(rel, "event_id", None)
        if ev_id is None or ev_id not in event_id_set:
            continue
        moved_relation_ids.append(str(getattr(rel, "id", "") or ""))
        if getattr(rel, "subject_entity_id", None) == original_id:
            rel.subject_entity_id = new_entity_id
        if getattr(rel, "object_entity_id", None) == original_id:
            rel.object_entity_id = new_entity_id

    action = KgEntityResolutionAction(
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
            "moved_event_entity_ids": [x for x in moved_assoc_ids if x],
            "moved_relation_ids": [x for x in moved_relation_ids if x],
            "new_entity_name": new_name,
            "moved_events": [str(eid) for eid in event_ids],
        },
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(action)

    try:
        db.add(
            AuditLog(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                actor_id=str(account_id or "").strip() or None,
                action="kg.entity.split",
                resource_type="kg_entity",
                resource_id=str(original_id),
                details={
                    "original_entity_id": str(original_id),
                    "new_entity_id": str(new_entity_id),
                    "moved_event_entity_edges": len([x for x in moved_assoc_ids if x]),
                    "moved_relations": len([x for x in moved_relation_ids if x]),
                },
            )
        )
    except Exception as exc:
        logger.debug("Ignoring non-critical KG API fallback failure: %s", exc)

    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug("Ignoring non-critical KG API fallback failure: %s", exc)
        raise

    return KGEntitySplitResponse(
        action_id=action.id,
        original_entity_id=original_id,
        new_entity_id=new_entity_id,
        stats={
            "moved_event_entity_edges": len([x for x in moved_assoc_ids if x]),
            "moved_relations": len([x for x in moved_relation_ids if x]),
        },
    )


@router.post("/entities/resolution/actions/{action_id}/undo", response_model=KGEntityResolutionUndoResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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
    # Vector side effects are controlled by settings (keep Milvus imports lazy).

    action = db.query(KgEntityResolutionAction).filter_by(tenant_id=tenant_id, id=action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Resolution action not found")

    if str(getattr(action, "status", "") or "").strip().lower() != "applied":
        raise HTTPException(status_code=409, detail="Resolution action is not in applied state")

    payload = dict(getattr(action, "payload", None) or {})
    action_kind = str(payload.get("action") or "").strip().lower()
    if action_kind not in {"merge", "split"}:
        raise HTTPException(status_code=400, detail="Unsupported resolution action for undo")

    restored_edges = 0
    restored_relations = 0
    redirect_removed = False
    deleted_new_entity = False

    source_id = None
    target_id = None

    if action_kind == "merge":
        source_id = _uuid_or_none(payload.get("source_entity_id"))
        target_id = _uuid_or_none(payload.get("target_entity_id"))
        if source_id is None or target_id is None:
            raise HTTPException(status_code=400, detail="Invalid action payload (missing entity ids)")

        updated_assoc_ids = {str(u) for u in _uuid_list(payload.get("event_entity_updated_ids")) if u}
        deleted_assoc_rows = _dict_list(payload.get("event_entity_deleted_rows"))
        updated_relation_ids = {str(u) for u in _uuid_list(payload.get("relation_updated_ids")) if u}
        deleted_relation_rows = _dict_list(payload.get("relation_deleted_rows"))
        redirect_created = bool(payload.get("redirect_created", False))
        vector_deleted = bool(payload.get("vector_deleted", False))

        # Restore updated association rows by id (best-effort).
        if updated_assoc_ids:
            for assoc in db.query(KgEventEntity).all():
                aid = str(getattr(assoc, "id", "") or "")
                if aid and aid in updated_assoc_ids:
                    assoc.entity_id = source_id
                    restored_edges += 1

        # Restore deleted association rows (dedupe deletions).
        for row in deleted_assoc_rows:
            rid = _uuid_or_none(row.get("id"))
            ev_id = _uuid_or_none(row.get("event_id"))
            if rid is None or ev_id is None:
                continue
            db.add(
                KgEventEntity(
                    id=rid,
                    event_id=ev_id,
                    entity_id=source_id,
                    weight=float(row.get("weight", 1.0) or 1.0),
                    role=(str(row.get("role")) if row.get("role") is not None else None),
                    extra_data=(row.get("extra_data") if isinstance(row.get("extra_data"), dict) else None),
                )
            )
            restored_edges += 1

        # Restore updated relations by id.
        if updated_relation_ids:
            for rel in db.query(KgRelation).filter_by(tenant_id=tenant_id).all():
                rid = str(getattr(rel, "id", "") or "")
                if not rid or rid not in updated_relation_ids:
                    continue

                # If we don't have a snapshot, conservatively swap target back to source.
                if getattr(rel, "subject_entity_id", None) == target_id:
                    rel.subject_entity_id = source_id
                if getattr(rel, "object_entity_id", None) == target_id:
                    rel.object_entity_id = source_id
                restored_relations += 1

        # Reinsert deleted relations.
        for row in deleted_relation_rows:
            rid = _uuid_or_none(row.get("id"))
            if rid is None:
                continue
            db.add(
                KgRelation(
                    id=rid,
                    tenant_id=tenant_id,
                    pipeline_hash=(str(row.get("pipeline_hash"))[:200] if row.get("pipeline_hash") else None),
                    document_id=_uuid_or_none(row.get("document_id")),
                    chunk_id=_uuid_or_none(row.get("chunk_id")),
                    event_id=_uuid_or_none(row.get("event_id")),
                    subject_entity_id=_uuid_or_none(row.get("subject_entity_id")) or source_id,
                    predicate=str(row.get("predicate") or "").strip() or "related_to",
                    predicate_raw=(str(row.get("predicate_raw"))[:200] if row.get("predicate_raw") else None),
                    object_entity_id=_uuid_or_none(row.get("object_entity_id")) or source_id,
                    confidence=float(row.get("confidence", 0.5) or 0.5),
                    qualifiers=(row.get("qualifiers") if isinstance(row.get("qualifiers"), dict) else None),
                    references=(row.get("references") if isinstance(row.get("references"), dict) else None),
                    extra_data=(row.get("extra_data") if isinstance(row.get("extra_data"), dict) else None),
                    created_at=datetime.now(UTC).replace(tzinfo=None),
                    updated_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            restored_relations += 1

        # Remove redirect created by this action so old ids no longer resolve.
        if redirect_created:
            row = db.query(KgEntityRedirect).filter_by(tenant_id=tenant_id, from_entity_id=source_id).first()
            if row and getattr(row, "to_entity_id", None) == target_id:
                db.delete(row)
                redirect_removed = True

        # Best-effort: restore entity vector if we deleted it.
        if vector_deleted and bool(getattr(settings, "KG_ENTITY_RESOLUTION_UPDATE_VECTORS_ENABLED", False)):
            try:
                from app.rag.kg.models import KgEntity  # noqa: WPS433
                from app.storage.vector.milvus import get_milvus_adapter, resolve_collection_name  # noqa: WPS433

                ent = db.query(KgEntity).filter_by(tenant_id=tenant_id, id=source_id).first()
                if ent is not None and getattr(ent, "vector", None):
                    collection = resolve_collection_name("kg_entities")
                    milvus = get_milvus_adapter(collection_name=collection, vector_field="embedding")
                    milvus.add_vectors(
                        items=[
                            {
                                "id": str(source_id),
                                "content": str(getattr(ent, "name", "") or ""),
                                "metadata": {
                                    "name": str(getattr(ent, "name", "") or ""),
                                    "normalized_name": str(getattr(ent, "normalized_name", "") or ""),
                                    "tenant_id": str(tenant_id),
                                    "type": str(getattr(ent, "type", "") or "unknown"),
                                    "description": str(getattr(ent, "description", "") or ""),
                                    "index_kind": "entity",
                                },
                            }
                        ],
                        embeddings=[list(ent.vector)],
                    )
            except Exception as exc:
                logger.debug("Ignoring non-critical KG API fallback failure: %s", exc)

    elif action_kind == "split":
        original_id = _uuid_or_none(payload.get("original_entity_id"))
        new_id = _uuid_or_none(payload.get("new_entity_id"))
        if original_id is None or new_id is None:
            raise HTTPException(status_code=400, detail="Invalid action payload (missing entity ids)")
        moved_assoc_ids = {str(x) for x in (payload.get("moved_event_entity_ids") or []) if str(x or "").strip()}
        moved_relation_ids = {str(x) for x in (payload.get("moved_relation_ids") or []) if str(x or "").strip()}

        if moved_assoc_ids:
            for assoc in db.query(KgEventEntity).all():
                aid = str(getattr(assoc, "id", "") or "")
                if aid and aid in moved_assoc_ids:
                    assoc.entity_id = original_id
                    restored_edges += 1

        if moved_relation_ids:
            for rel in db.query(KgRelation).filter_by(tenant_id=tenant_id).all():
                rid = str(getattr(rel, "id", "") or "")
                if rid and rid in moved_relation_ids:
                    if getattr(rel, "subject_entity_id", None) == new_id:
                        rel.subject_entity_id = original_id
                    if getattr(rel, "object_entity_id", None) == new_id:
                        rel.object_entity_id = original_id
                    restored_relations += 1

        # Best-effort prune: if the split-created entity is now orphaned, remove it so undo
        # truly returns the graph to the pre-split shape.
        try:
            from app.rag.kg.models import KgEntity, KgEntityAlias  # noqa: WPS433

            remaining_assocs = db.query(KgEventEntity).filter_by(entity_id=new_id).all()
            remaining_rel_subj = db.query(KgRelation).filter_by(tenant_id=tenant_id, subject_entity_id=new_id).all()
            remaining_rel_obj = db.query(KgRelation).filter_by(tenant_id=tenant_id, object_entity_id=new_id).all()
            remaining_aliases = db.query(KgEntityAlias).filter_by(
                tenant_id=tenant_id, canonical_entity_id=new_id
            ).all()
            remaining_redirects_from = db.query(KgEntityRedirect).filter_by(
                tenant_id=tenant_id, from_entity_id=new_id
            ).all()
            remaining_redirects_to = db.query(KgEntityRedirect).filter_by(tenant_id=tenant_id, to_entity_id=new_id).all()
            if (
                not remaining_assocs
                and not remaining_rel_subj
                and not remaining_rel_obj
                and not remaining_aliases
                and not remaining_redirects_from
                and not remaining_redirects_to
            ):
                ent = db.query(KgEntity).filter_by(tenant_id=tenant_id, id=new_id).first()
                if ent is not None:
                    db.delete(ent)
                    deleted_new_entity = True
        except Exception as exc:
            logger.debug("Ignoring non-critical KG API fallback failure: %s", exc)

        source_id = original_id
        target_id = new_id

    action.status = "reverted"
    action.reversed_at = datetime.now(UTC).replace(tzinfo=None)
    action.reversed_by = str(account_id or "").strip() or None

    try:
        db.add(
            AuditLog(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                actor_id=str(account_id or "").strip() or None,
                action="kg.entity.merge.undo" if action_kind == "merge" else "kg.entity.split.undo",
                resource_type="kg_entity_resolution_action",
                resource_id=str(action_id),
                details={"source_entity_id": str(source_id), "target_entity_id": str(target_id)},
            )
        )
    except Exception as exc:
        logger.debug("Ignoring non-critical KG API fallback failure: %s", exc)

    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug("Ignoring non-critical KG API fallback failure: %s", exc)
        raise

    return KGEntityResolutionUndoResponse(
        action_id=action.id,
        status=str(action.status or ""),
        stats={
            "restored_event_entity_edges": int(restored_edges),
            "restored_relations": int(restored_relations),
            "redirect_removed": bool(redirect_removed),
            "deleted_new_entity": bool(deleted_new_entity),
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
            logger.debug("Ignoring non-critical KG API fallback failure: %s", exc)

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


@router.post("/documents/{document_id}/extract", response_model=KGExtractResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def run_kg_extraction_for_document(
    document_id: UUID,
    response: Response,
    async_mode: Annotated[bool, Query(alias="async")] = False,
    pipeline_hash: Annotated[str | None, Query(
        min_length=1,
        max_length=200,
        description="Optional pipeline hash override (defaults to active pipeline)",
    )] = None,
    replace_existing: Annotated[bool | None, Query(description="Replace previously extracted events for this document")] = None,
    prune_orphan_entities: Annotated[bool | None, Query(description="Prune entities with no remaining event links")] = None,
    extract_relations: Annotated[bool | None, Query(description="Extract entity relations (triples) (override settings)")] = None,
    extract_skills: Annotated[bool | None, Query(description="Extract Skill/SOP entities (override settings)")] = None,
    extraction_backend: Annotated[str | None, Query(description="Extraction backend override: llm, gliner, hybrid, heuristic")] = None,
    prompt_template_id: Annotated[UUID | None, Query()] = None,
    prompt_template_key: Annotated[str | None, Query()] = None,
    prompt_ab_experiment_key: Annotated[str | None, Query()] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Trigger KG extraction for a processed document (rebuilds events/entities from chunks).
    """
    _ensure_enabled()
    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)

    chunks = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.document_id == document_id,
            DocumentChunk.tenant_id == tenant_id,
        )
        .order_by(DocumentChunk.chunk_index)
        .all()
    )
    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="Document has no chunks yet. Process the document first.",
        )

    # Versioning: avoid mixing multiple chunk versions when the document has been
    # re-processed under different pipeline hashes. Default to the active pipeline
    # version stored in document metadata.
    # NOTE: tests call this route handler directly (without FastAPI request parsing),
    # so `pipeline_hash` can be a `fastapi.Query` object. Treat non-strings as unset.
    explicit_ph = (pipeline_hash.strip() if isinstance(pipeline_hash, str) else "") or None
    selected_ph = explicit_ph or _doc_pipeline_hash(getattr(document, "doc_metadata", None) or {})
    if selected_ph:
        scoped = [c for c in chunks if _chunk_matches_pipeline(c, document_id=document_id, pipeline_hash=selected_ph)]
        if scoped:
            chunks = scoped

    eff_prompt_template_id = prompt_template_id
    if eff_prompt_template_id is None:
        raw_tid = (getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_ID", "") or "").strip()
        if raw_tid:
            try:
                eff_prompt_template_id = UUID(raw_tid)
            except Exception:
                eff_prompt_template_id = None

    eff_prompt_template_key = (prompt_template_key or "").strip() or (getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_KEY", "") or "").strip() or None
    eff_prompt_ab_experiment_key = (prompt_ab_experiment_key or "").strip() or (getattr(settings, "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY", "") or "").strip() or None

    eff_replace_existing = bool(
        settings.KG_EXTRACT_REPLACE_EXISTING if replace_existing is None else replace_existing
    )
    eff_prune_orphans = bool(
        settings.KG_EXTRACT_PRUNE_ORPHAN_ENTITIES if prune_orphan_entities is None else prune_orphan_entities
    )
    # Route handlers are sometimes invoked directly in unit tests; FastAPI `Query(...)` defaults
    # are not JSON-serializable and should not leak into downstream calls or audit logs.
    eff_extract_relations: bool | None = extract_relations if isinstance(extract_relations, bool) else None
    eff_extract_skills: bool | None = extract_skills if isinstance(extract_skills, bool) else None

    # If async=true, enqueue KG extraction (default remains synchronous for compatibility).
    if bool(async_mode):
        if not bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
            raise HTTPException(status_code=400, detail="Task queue is disabled (TASK_QUEUE_ENABLED=false)")
        try:
            from app.tasks.queue import enqueue_kg_extraction

            # Versioning: use the selected pipeline version (defaults to active_pipeline_hash)
            # so async job dedupe/locks don't conflate different document versions.
            pipeline_hash_for_job = selected_ph or (document.doc_metadata or {}).get("pipeline_hash") or "unknown"
            pipeline_hash_for_job = str(pipeline_hash_for_job).strip() or "unknown"
            job_id = f"kg:{tenant_id}:{document_id}:{pipeline_hash_for_job}"
            task_id = await enqueue_kg_extraction(
                tenant_id=tenant_id,
                document_id=document_id,
                requested_by=account_id,
                job_id=job_id,
                pipeline_hash=pipeline_hash_for_job,
                replace_existing=eff_replace_existing,
                prune_orphan_entities=eff_prune_orphans,
                extract_relations=eff_extract_relations,
                extract_skills=eff_extract_skills,
            )
            if task_id:
                meta = dict(document.doc_metadata or {})
                meta["kg_task_id"] = task_id
                document.doc_metadata = meta
                db.commit()
                db.refresh(document)

            # Best-effort audit log: extraction enqueued (PII-minimal).
            try:
                from app.models.audit_log import AuditLog

                db.add(
                    AuditLog(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        actor_id=str(account_id or "").strip() or None,
                        action="kg.document.extract.enqueue",
                        resource_type="document",
                        resource_id=str(document_id),
                        details={
                            "async": True,
                            "task_id": str(task_id) if task_id else None,
                            "pipeline_hash": str(pipeline_hash_for_job),
                            "replace_existing": bool(eff_replace_existing),
                            "prune_orphan_entities": bool(eff_prune_orphans),
                            "extract_relations": eff_extract_relations,
                            "extract_skills": eff_extract_skills,
                        },
                    )
                )
                db.commit()
            except Exception:
                with contextlib.suppress(Exception):
                    db.rollback()

            response.status_code = 202
            if task_id:
                response.headers["X-Task-Id"] = str(task_id)
            return KGExtractResponse(document_id=document_id, chunk_count=len(chunks), event_count=0)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=f"Failed to enqueue KG extraction: {str(exc)[:200]}") from exc

    try:
        events = await extract_events(
            [c.id for c in chunks],
            tenant_id=tenant_id,
            chunks=chunks,
            prompt_template_id=eff_prompt_template_id,
            prompt_template_key=eff_prompt_template_key,
            prompt_ab_experiment_key=eff_prompt_ab_experiment_key,
            ab_user_key=account_id,
            extract_relations=eff_extract_relations,
            extract_skills=eff_extract_skills,
            extraction_backend=(str(extraction_backend).strip() if isinstance(extraction_backend, str) else None),
            replace_existing=eff_replace_existing,
            prune_orphan_entities=eff_prune_orphans,
        )
    except ConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"KG extraction failed: {str(exc)[:200]}") from exc

    # Best-effort audit log: extraction completed (PII-minimal).
    try:
        from app.models.audit_log import AuditLog

        db.add(
            AuditLog(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                actor_id=str(account_id or "").strip() or None,
                action="kg.document.extract",
                resource_type="document",
                resource_id=str(document_id),
                details={
                    "async": False,
                    "pipeline_hash": selected_ph,
                    "chunk_count": int(len(chunks)),
                    "event_count": int(len(events or [])),
                    "replace_existing": bool(eff_replace_existing),
                    "prune_orphan_entities": bool(eff_prune_orphans),
                    "extract_relations": eff_extract_relations,
                    "extract_skills": eff_extract_skills,
                },
            )
        )
        db.commit()
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()

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
