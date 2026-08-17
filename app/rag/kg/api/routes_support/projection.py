"""Graph projection and generic helpers for the KG API routes.

Split out of ``app.rag.kg.api.routes`` (see ``app.rag.kg.api.routes_support``).
Covers graph projection (nodes/links/limits/pipeline scoping), document ACL
resolution, and the generic serialization/uuid utilities shared by the other
submodules. Function-local (deferred) imports are preserved verbatim to avoid
changing import-time behavior.
"""

import hashlib
import time
import zlib
from collections import Counter
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.kg.api.routes_support.common import logger
from app.rag.kg.api.routes_support.schemas import (
    KGGraphBuildResult,
    KGGraphProjectionLimits,
    KGGraphProjectionParams,
)
from app.rag.kg.provenance import build_event_entity_provenance
from app.rag.kg.schemas import KGGraphResponse
from app.services.document_access import filter_allowed_document_ids, list_accessible_document_ids
from app.services.metrics_logger import log_metrics


def _log_kg_api_metric(event: str, **fields: object) -> None:
    if not settings.KG_API_METRICS_ENABLED:
        return
    try:
        payload: dict[str, object] = {"event": event}
        payload.update({k: v for k, v in fields.items() if v is not None})
        log_metrics(payload)
    except Exception as exc:
        # Best-effort only; metrics must never break the API.
        logger.debug("Failed to emit KG API metric %s: %s", event, exc)


def _stable_group_for(entity_type: str, *, buckets: int = 24) -> int:
    """Stable group id for frontend coloring (deterministic across requests)."""
    key = (entity_type or "unknown").strip().lower() or "unknown"
    buckets_i = max(1, int(buckets))
    digest = zlib.crc32(key.encode("utf-8"))
    return int(digest % buckets_i) + 1


def _kg_event_node(ev: Any, event_degree: Counter[str], *, center_id: UUID | None = None) -> dict[str, Any]:
    ev_id = str(ev.id)
    meta: dict[str, Any] = {
        "kind": "event",
        "document_id": str(ev.document_id) if ev.document_id else "",
        "chunk_id": str(ev.chunk_id) if ev.chunk_id else "",
    }
    if center_id is not None:
        meta["center"] = ev_id == str(center_id)
    return {
        "id": ev_id,
        "label": (ev.title or "").strip() or ev_id,
        "group": 0,
        "val": max(1, int(event_degree.get(ev_id, 0))),
        "meta": meta,
    }


def _kg_entity_node(ent: Any, entity_hit_count: Counter[str], *, center_id: UUID | None = None) -> dict[str, Any]:
    ent_id = str(ent.id)
    meta: dict[str, Any] = {
        "kind": "entity",
        "type": getattr(ent, "type", None),
        "normalized_name": getattr(ent, "normalized_name", None),
    }
    if center_id is not None:
        meta["center"] = ent_id == str(center_id)
    return {
        "id": ent_id,
        "label": (ent.name or "").strip() or ent_id,
        "group": _stable_group_for(getattr(ent, "type", "") or "unknown"),
        "val": max(1, int(entity_hit_count.get(ent_id, 0))),
        "meta": meta,
    }


def _kg_event_entity_link(assoc: Any, ent: Any) -> dict[str, Any]:
    ent_id = str(ent.id)
    raw_extra = getattr(assoc, "extra_data", None)
    edge_meta = {"kind": "event_entity"}
    edge_meta.update(
        build_event_entity_provenance(
            document_id=(raw_extra.get("document_id") if isinstance(raw_extra, dict) else None),
            chunk_id=(raw_extra.get("chunk_id") if isinstance(raw_extra, dict) else None),
            references=(raw_extra if isinstance(raw_extra, dict) else None),
        )
    )
    return {
        "source": str(assoc.event_id),
        "target": ent_id,
        "label": (assoc.role or "").strip() or getattr(ent, "type", "") or "mentions",
        "weight": float(getattr(assoc, "weight", 1.0) or 1.0),
        "meta": edge_meta,
    }


def _kg_relation_link(rel: Any) -> dict[str, Any] | None:
    subj = str(getattr(rel, "subject_entity_id", "") or "")
    obj = str(getattr(rel, "object_entity_id", "") or "")
    if not subj or not obj:
        return None
    pred = str(getattr(rel, "predicate", "") or "").strip()
    if not pred:
        return None
    conf_raw = getattr(rel, "confidence", None)
    try:
        conf = float(conf_raw) if conf_raw is not None else 1.0
    except Exception:
        conf = 1.0
    return {
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


def _kg_event_degrees(db: Session, kg_event_entity_model: Any, event_ids: list[UUID]) -> Counter[str]:
    from sqlalchemy import func

    degree_rows = (
        db.query(kg_event_entity_model.event_id, func.count(kg_event_entity_model.entity_id).label("cnt"))
        .filter(kg_event_entity_model.event_id.in_(event_ids))
        .group_by(kg_event_entity_model.event_id)
        .all()
    )
    return Counter({str(ev_id): int(cnt or 0) for ev_id, cnt in degree_rows})


def _kg_allowed_entities(
    db: Session,
    kg_event_entity_model: Any,
    event_ids: list[UUID],
    *,
    max_entities: int,
) -> tuple[list[UUID], set[str], Counter[str]]:
    from sqlalchemy import func

    ent_rows = (
        db.query(kg_event_entity_model.entity_id, func.count(kg_event_entity_model.event_id).label("cnt"))
        .filter(kg_event_entity_model.event_id.in_(event_ids))
        .group_by(kg_event_entity_model.entity_id)
        .order_by(func.count(kg_event_entity_model.event_id).desc())
        .limit(int(max_entities))
        .all()
    )
    allowed_entity_ids = [row[0] for row in ent_rows if row and row[0]]
    return (
        allowed_entity_ids,
        {str(eid) for eid in allowed_entity_ids},
        Counter({str(ent_id): int(cnt or 0) for ent_id, cnt in ent_rows}),
    )


def _kg_event_entity_rows(
    db: Session,
    kg_event_entity_model: Any,
    kg_entity_model: Any,
    event_ids: list[UUID],
    allowed_entity_ids: list[UUID],
) -> list[Any]:
    return (
        db.query(kg_event_entity_model, kg_entity_model)
        .join(kg_entity_model, kg_entity_model.id == kg_event_entity_model.entity_id)
        .filter(
            kg_event_entity_model.event_id.in_(event_ids),
            kg_event_entity_model.entity_id.in_(allowed_entity_ids),
        )
        .all()
    )


def _kg_entity_cooccurrence_counts(
    rows: list[Any],
    allowed_entity_id_strs: set[str],
    *,
    per_event_entity_cap: int,
) -> Counter[tuple[str, str]]:
    from itertools import combinations

    event_to_entities: dict[str, set[str]] = {}
    for assoc, ent in rows:
        ent_id = str(ent.id)
        if ent_id in allowed_entity_id_strs:
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
    return co_counts


def _add_kg_entity_cooccurrence_links(
    *,
    links: list[dict[str, Any]],
    rows: list[Any],
    allowed_entity_id_strs: set[str],
    max_links: int,
    max_entity_links: int,
    min_shared_events: int,
) -> int:
    per_event_entity_cap = int(getattr(settings, "KG_ENTITY_LINK_MAX_ENTITIES_PER_EVENT", 60) or 60)
    per_event_entity_cap = max(0, min(per_event_entity_cap, 500))
    co_counts = _kg_entity_cooccurrence_counts(
        rows,
        allowed_entity_id_strs,
        per_event_entity_cap=per_event_entity_cap,
    )

    links_added = 0
    remaining_budget = max(0, int(max_links) - len(links))
    edge_limit = min(int(max_entity_links), remaining_budget)
    for (a, b), cnt in co_counts.most_common(edge_limit):
        if int(cnt) < int(min_shared_events) or len(links) >= int(max_links):
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
        links_added += 1
    return links_added


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


def _kg_limit_value(value: int | None, default: int) -> int:
    return default if value is None else value


def _kg_graph_limits(params: KGGraphProjectionParams, *, expand: bool = False) -> KGGraphProjectionLimits:
    default_max_events = 50 if expand else 200
    default_max_links = 5000 if expand else 2000
    default_max_entity_links = 2000 if expand else 1000

    return KGGraphProjectionLimits(
        max_events=_kg_limit_value(params.max_events, default_max_events),
        max_entities=_kg_limit_value(params.max_entities, 400),
        max_links=_kg_limit_value(params.max_links, default_max_links),
        include_entity_links=bool(params.include_entity_links),
        include_relation_links=bool(params.include_relation_links),
        min_shared_events=_kg_limit_value(params.min_shared_events, 2),
        max_entity_links=_kg_limit_value(params.max_entity_links, default_max_entity_links),
    )


def _log_kg_graph_metric(
    metric: str,
    *,
    t0: float,
    tenant_id: UUID,
    docs: int,
    events: int,
    entities: int,
    links: int,
) -> None:
    _log_kg_api_metric(
        metric,
        tenant_id=str(tenant_id),
        docs=docs,
        events=events,
        entities=entities,
        links=links,
        elapsed_sec=round(float(time.perf_counter() - t0), 3),
    )


def _empty_kg_graph_response(
    *,
    metric: str,
    t0: float,
    tenant_id: UUID,
    docs: int,
    stats: dict[str, Any],
) -> KGGraphResponse:
    out = KGGraphResponse(nodes=[], links=[], stats=stats)
    _log_kg_graph_metric(metric, t0=t0, tenant_id=tenant_id, docs=docs, events=0, entities=0, links=0)
    return out


def _load_kg_projection_events(
    db: Session,
    source_event_model: Any,
    *,
    tenant_id: UUID,
    allowed_doc_ids: list[UUID],
    pipeline_hash: str | None,
    max_events: int,
) -> list[Any]:
    events_q = db.query(source_event_model).filter(
        source_event_model.tenant_id == tenant_id,
        source_event_model.document_id.in_(allowed_doc_ids),
    )
    events_q = _apply_event_pipeline_scope(events_q, pipeline_hash=pipeline_hash)
    return events_q.order_by(source_event_model.updated_at.desc()).limit(int(max_events)).all()


def _event_entity_nodes_and_links(
    *,
    events: list[Any],
    rows: list[tuple[Any, Any]],
    event_degree: Counter[str],
    allowed_entity_id_strs: set[str],
    entity_hit_count: Counter[str],
    max_links: int,
    center_id: UUID | None = None,
) -> tuple[list[dict], list[dict], set[str]]:
    nodes = [_kg_event_node(ev, event_degree, center_id=center_id) for ev in events]
    links: list[dict] = []
    seen_entities: set[str] = set()
    for assoc, ent in rows:
        ent_id = str(ent.id)
        if ent_id not in allowed_entity_id_strs:
            continue
        if ent_id not in seen_entities:
            seen_entities.add(ent_id)
            nodes.append(_kg_entity_node(ent, entity_hit_count, center_id=center_id))
        if len(links) < int(max_links):
            links.append(_kg_event_entity_link(assoc, ent))
    return nodes, links, seen_entities


def _append_relation_links(
    db: Session,
    relation_model: Any,
    *,
    tenant_id: UUID,
    allowed_doc_ids: list[UUID],
    allowed_entity_ids: list[UUID],
    pipeline_hash: str | None,
    links: list[dict],
    max_links: int,
) -> int:
    remaining_budget = max(0, int(max_links) - len(links))
    if remaining_budget <= 0:
        return 0
    rel_q = db.query(relation_model).filter(
        relation_model.tenant_id == tenant_id,
        relation_model.document_id.in_(allowed_doc_ids),
        relation_model.subject_entity_id.in_(allowed_entity_ids),
        relation_model.object_entity_id.in_(allowed_entity_ids),
    )
    rel_q = _apply_relation_pipeline_scope(rel_q, pipeline_hash=pipeline_hash)
    added = 0
    for rel in rel_q.order_by(relation_model.updated_at.desc()).limit(int(remaining_budget)).all():
        if len(links) >= int(max_links):
            break
        link = _kg_relation_link(rel)
        if link is None:
            continue
        links.append(link)
        added += 1
    return added


def _build_kg_graph_response_from_events(
    db: Session,
    *,
    tenant_id: UUID,
    allowed_doc_ids: list[UUID],
    events: list[Any],
    limits: KGGraphProjectionLimits,
    pipeline_hash: str | None,
    center_id: UUID | None = None,
) -> KGGraphBuildResult:
    from app.rag.kg.models import KgEntity, KgEventEntity, KgRelation

    event_ids = [event.id for event in events]
    event_degree = _kg_event_degrees(db, KgEventEntity, event_ids)
    allowed_entity_ids, allowed_entity_id_strs, entity_hit_count = _kg_allowed_entities(
        db,
        KgEventEntity,
        event_ids,
        max_entities=int(limits.max_entities),
    )
    if not allowed_entity_ids:
        nodes = [_kg_event_node(ev, event_degree, center_id=center_id) for ev in events]
        return KGGraphBuildResult(
            response=KGGraphResponse(nodes=nodes, links=[], stats={"events": len(events), "entities": 0, "links": 0}),
            event_entity_links=0,
            relation_links_added=0,
            entity_links_added=0,
        )

    rows = _kg_event_entity_rows(db, KgEventEntity, KgEntity, event_ids, allowed_entity_ids)
    nodes, links, seen_entities = _event_entity_nodes_and_links(
        events=events,
        rows=rows,
        event_degree=event_degree,
        allowed_entity_id_strs=allowed_entity_id_strs,
        entity_hit_count=entity_hit_count,
        max_links=int(limits.max_links),
        center_id=center_id,
    )
    event_entity_links = len(links)
    relation_links_added = 0
    if limits.include_relation_links and len(links) < int(limits.max_links):
        relation_links_added = _append_relation_links(
            db,
            KgRelation,
            tenant_id=tenant_id,
            allowed_doc_ids=allowed_doc_ids,
            allowed_entity_ids=allowed_entity_ids,
            pipeline_hash=pipeline_hash,
            links=links,
            max_links=int(limits.max_links),
        )

    entity_links_added = 0
    if limits.include_entity_links and int(limits.max_entity_links) > 0 and len(links) < int(limits.max_links):
        entity_links_added = _add_kg_entity_cooccurrence_links(
            links=links,
            rows=rows,
            allowed_entity_id_strs=allowed_entity_id_strs,
            max_links=int(limits.max_links),
            max_entity_links=int(limits.max_entity_links),
            min_shared_events=int(limits.min_shared_events),
        )

    stats: dict[str, Any] = {
        "events": len(events),
        "entities": len(seen_entities),
        "links": min(len(links), int(limits.max_links)),
        "event_entity_links": event_entity_links,
        "entity_relation_links": relation_links_added,
        "entity_entity_links": entity_links_added,
    }
    if center_id is not None:
        stats["center_node_id"] = str(center_id)
    return KGGraphBuildResult(
        response=KGGraphResponse(nodes=nodes, links=links, stats=stats),
        event_entity_links=event_entity_links,
        relation_links_added=relation_links_added,
        entity_links_added=entity_links_added,
    )


def _related_event_ids_for_center_event(
    db: Session,
    event_entity_model: Any,
    source_event_model: Any,
    *,
    tenant_id: UUID,
    allowed_doc_ids: list[UUID],
    center_event: Any,
    pipeline_hash: str | None,
    max_events: int,
) -> list[UUID]:
    entity_ids = (
        db.query(event_entity_model.entity_id).filter(event_entity_model.event_id == center_event.id).limit(2000).all()
    )
    entity_ids_flat = [row[0] for row in entity_ids]
    if not entity_ids_flat or int(max_events) <= 1:
        return []
    related_q = (
        db.query(event_entity_model.event_id)
        .join(source_event_model, source_event_model.id == event_entity_model.event_id)
        .filter(
            source_event_model.tenant_id == tenant_id,
            source_event_model.document_id.in_(allowed_doc_ids),
            event_entity_model.entity_id.in_(entity_ids_flat),
            event_entity_model.event_id != center_event.id,
        )
    )
    related_q = _apply_event_pipeline_scope(related_q, pipeline_hash=pipeline_hash)
    return [
        row[0]
        for row in related_q.order_by(source_event_model.updated_at.desc()).limit(max(0, int(max_events) - 1)).all()
    ]


def _load_events_by_ids(
    db: Session,
    source_event_model: Any,
    *,
    tenant_id: UUID,
    allowed_doc_ids: list[UUID],
    event_ids: list[UUID],
    pipeline_hash: str | None,
    max_events: int,
) -> list[Any]:
    if not event_ids:
        return []
    events_q = db.query(source_event_model).filter(
        source_event_model.tenant_id == tenant_id,
        source_event_model.id.in_(event_ids),
        source_event_model.document_id.in_(allowed_doc_ids),
    )
    events_q = _apply_event_pipeline_scope(events_q, pipeline_hash=pipeline_hash)
    return events_q.order_by(source_event_model.updated_at.desc()).limit(int(max_events)).all()


def _event_ids_for_center_entity(
    db: Session,
    event_entity_model: Any,
    source_event_model: Any,
    *,
    tenant_id: UUID,
    allowed_doc_ids: list[UUID],
    entity_id: UUID,
    pipeline_hash: str | None,
    max_events: int,
) -> list[UUID]:
    ev_ids_q = (
        db.query(event_entity_model.event_id)
        .join(source_event_model, source_event_model.id == event_entity_model.event_id)
        .filter(
            source_event_model.tenant_id == tenant_id,
            source_event_model.document_id.in_(allowed_doc_ids),
            event_entity_model.entity_id == entity_id,
        )
    )
    ev_ids_q = _apply_event_pipeline_scope(ev_ids_q, pipeline_hash=pipeline_hash)
    return [row[0] for row in ev_ids_q.order_by(source_event_model.updated_at.desc()).limit(int(max_events)).all()]


def _expanded_kg_events_for_node(
    db: Session,
    *,
    tenant_id: UUID,
    node_id: UUID,
    allowed_doc_ids: list[UUID],
    pipeline_hash: str | None,
    max_events: int,
) -> tuple[list[Any], str | None]:
    from app.rag.kg.models import KgEntity, KgEventEntity, KgSourceEvent

    center_event_q = db.query(KgSourceEvent).filter(
        KgSourceEvent.tenant_id == tenant_id,
        KgSourceEvent.id == node_id,
        KgSourceEvent.document_id.in_(allowed_doc_ids),
    )
    center_event = _apply_event_pipeline_scope(center_event_q, pipeline_hash=pipeline_hash).first()
    if center_event:
        related_event_ids = _related_event_ids_for_center_event(
            db,
            KgEventEntity,
            KgSourceEvent,
            tenant_id=tenant_id,
            allowed_doc_ids=allowed_doc_ids,
            center_event=center_event,
            pipeline_hash=pipeline_hash,
            max_events=max_events,
        )
        return (
            _load_events_by_ids(
                db,
                KgSourceEvent,
                tenant_id=tenant_id,
                allowed_doc_ids=allowed_doc_ids,
                event_ids=[center_event.id] + related_event_ids,
                pipeline_hash=pipeline_hash,
                max_events=max_events,
            ),
            None,
        )

    center_entity = db.query(KgEntity).filter(KgEntity.tenant_id == tenant_id, KgEntity.id == node_id).first()
    if not center_entity:
        raise HTTPException(status_code=404, detail="KG node not found")
    event_ids = _event_ids_for_center_entity(
        db,
        KgEventEntity,
        KgSourceEvent,
        tenant_id=tenant_id,
        allowed_doc_ids=allowed_doc_ids,
        entity_id=center_entity.id,
        pipeline_hash=pipeline_hash,
        max_events=max_events,
    )
    if not event_ids:
        return [], "no_related_events"
    return (
        _load_events_by_ids(
            db,
            KgSourceEvent,
            tenant_id=tenant_id,
            allowed_doc_ids=allowed_doc_ids,
            event_ids=event_ids,
            pipeline_hash=pipeline_hash,
            max_events=max_events,
        ),
        None,
    )
