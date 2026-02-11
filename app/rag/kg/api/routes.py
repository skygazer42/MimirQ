import asyncio
import zlib
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.core.errors import ConfigError
from app.rag.kg.pipeline import extract_events, kg_search
from app.rag.kg.schemas import (
    KGDeleteResponse,
    KGEntityDetailResponse,
    KGEntityItem,
    KGEventDetailResponse,
    KGEventEntityItem,
    KGEventItem,
    KGExtractResponse,
    KGGraphNode,
    KGGraphResponse,
    KGSearchRequest,
    KGSearchResponse,
    KGStatsResponse,
)
from app.services.dataset_service import DatasetService
from app.services.document_access import filter_allowed_document_ids, list_accessible_document_ids

router = APIRouter()


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


def _resolve_allowed_documents(
    *,
    document_ids: list[UUID] | None,
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
    return list_accessible_document_ids(db, tenant_id, account_id, status="completed", limit=eff_limit)


@router.get("/graph", response_model=KGGraphResponse)
async def get_kg_graph(
    document_ids: list[UUID] | None = Query(default=None),
    max_events: int = Query(default=200, ge=1, le=2000),
    max_entities: int = Query(default=400, ge=1, le=5000),
    max_links: int = Query(default=2000, ge=1, le=20000),
    include_entity_links: bool = Query(default=False, description="Include entity-entity co-occurrence links"),
    min_shared_events: int = Query(default=2, ge=1, le=100),
    max_entity_links: int = Query(default=1000, ge=0, le=20000),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Return a graph-friendly projection of KG tables for visualization.

    Notes:
    - Requires KG_ENABLED=true.
    - If document_ids is not provided, it falls back to the current account's accessible documents.
    - The response is intentionally lightweight and capped by max_* params.
    """
    _ensure_enabled()

    allowed_doc_ids: list[UUID]
    allowed_doc_ids = _resolve_allowed_documents(
        document_ids=document_ids,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )

    if not allowed_doc_ids:
        return KGGraphResponse(nodes=[], links=[], stats={"reason": "no_accessible_documents"})

    from collections import Counter

    from sqlalchemy import func

    from app.rag.kg.models import KgEntity, KgEventEntity, KgSourceEvent
    from app.rag.kg.provenance import build_event_entity_provenance

    events = (
        db.query(KgSourceEvent)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
        )
        .order_by(KgSourceEvent.updated_at.desc())
        .limit(int(max_events))
        .all()
    )

    if not events:
        return KGGraphResponse(nodes=[], links=[], stats={"events": 0, "entities": 0, "links": 0})

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
        return KGGraphResponse(nodes=nodes, links=[], stats={"events": len(events), "entities": 0, "links": 0})

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

    entity_links_added = 0
    base_link_count = len(links)
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

    return KGGraphResponse(
        nodes=nodes,
        links=links,
        stats={
            "events": len(events),
            "entities": len(seen_entities),
            "links": min(len(links), int(max_links)),
            "event_entity_links": base_link_count,
            "entity_entity_links": entity_links_added,
        },
    )


@router.get("/graph/expand", response_model=KGGraphResponse)
async def expand_kg_graph(
    node_id: UUID = Query(..., description="Center node id (KgSourceEvent.id or KgEntity.id)"),
    document_ids: list[UUID] | None = Query(default=None),
    max_events: int = Query(default=50, ge=1, le=500),
    max_entities: int = Query(default=400, ge=1, le=5000),
    max_links: int = Query(default=5000, ge=1, le=20000),
    include_entity_links: bool = Query(default=False, description="Include entity-entity co-occurrence links"),
    min_shared_events: int = Query(default=2, ge=1, le=100),
    max_entity_links: int = Query(default=2000, ge=0, le=20000),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Expand a single node (event/entity) into a small neighborhood subgraph.

    - Requires KG_ENABLED=true.
    - Enforces document-level access control.
    """
    _ensure_enabled()

    allowed_doc_ids = _resolve_allowed_documents(
        document_ids=document_ids,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    if not allowed_doc_ids:
        return KGGraphResponse(nodes=[], links=[], stats={"reason": "no_accessible_documents"})

    from collections import Counter

    from app.rag.kg.models import KgEntity, KgEventEntity, KgSourceEvent
    from app.rag.kg.provenance import build_event_entity_provenance

    # Determine node kind: event (scoped by allowed documents) or entity (tenant-scoped).
    center_event = (
        db.query(KgSourceEvent)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.id == node_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
        )
        .first()
    )

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
            related_event_ids = [
                row[0]
                for row in (
                    db.query(KgEventEntity.event_id)
                    .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
                    .filter(
                        KgSourceEvent.tenant_id == tenant_id,
                        KgSourceEvent.document_id.in_(allowed_doc_ids),
                        KgEventEntity.entity_id.in_(entity_ids_flat),
                        KgEventEntity.event_id != center_event.id,
                    )
                    .order_by(KgSourceEvent.updated_at.desc())
                    .limit(max(0, int(max_events) - 1))
                    .all()
                )
            ]

        event_ids = [center_event.id] + related_event_ids
        events = (
            db.query(KgSourceEvent)
            .filter(
                KgSourceEvent.tenant_id == tenant_id,
                KgSourceEvent.id.in_(event_ids),
                KgSourceEvent.document_id.in_(allowed_doc_ids),
            )
            .order_by(KgSourceEvent.updated_at.desc())
            .limit(int(max_events))
            .all()
        )
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

        event_ids = [
            row[0]
            for row in (
                db.query(KgEventEntity.event_id)
                .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
                .filter(
                    KgSourceEvent.tenant_id == tenant_id,
                    KgSourceEvent.document_id.in_(allowed_doc_ids),
                    KgEventEntity.entity_id == center_entity.id,
                )
                .order_by(KgSourceEvent.updated_at.desc())
                .limit(int(max_events))
                .all()
            )
        ]
        if not event_ids:
            return KGGraphResponse(nodes=[], links=[], stats={"reason": "no_related_events"})

        events = (
            db.query(KgSourceEvent)
            .filter(
                KgSourceEvent.tenant_id == tenant_id,
                KgSourceEvent.id.in_(event_ids),
                KgSourceEvent.document_id.in_(allowed_doc_ids),
            )
            .order_by(KgSourceEvent.updated_at.desc())
            .limit(int(max_events))
            .all()
        )

    if not events:
        return KGGraphResponse(nodes=[], links=[], stats={"events": 0, "entities": 0, "links": 0})

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
        return KGGraphResponse(nodes=nodes, links=[], stats={"events": len(events), "entities": 0, "links": 0})

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
    base_link_count = len(links)
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

    return KGGraphResponse(
        nodes=nodes,
        links=links,
        stats={
            "center_node_id": str(node_id),
            "events": len(events),
            "entities": len(seen_entities),
            "links": min(len(links), int(max_links)),
            "event_entity_links": base_link_count,
            "entity_entity_links": entity_links_added,
        },
    )


@router.get("/graph/search", response_model=list[KGGraphNode])
async def search_kg_graph_nodes(
    q: str = Query(..., min_length=1, description="Search query"),
    kind: str = Query(default="all", description="entity | event | all"),
    limit: int = Query(default=20, ge=1, le=100),
    document_ids: list[UUID] | None = Query(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Search KG nodes (entities/events) for UI autocomplete / quick jump.
    """
    _ensure_enabled()

    allowed_doc_ids = _resolve_allowed_documents(
        document_ids=document_ids,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )

    from sqlalchemy import or_

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
        ents = (
            db.query(KgEntity)
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
            .distinct()
            .order_by(KgEntity.updated_at.desc())
            .limit(int(limit))
            .all()
        )
        for ent in ents:
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
        events = (
            db.query(KgSourceEvent)
            .filter(
                KgSourceEvent.tenant_id == tenant_id,
                KgSourceEvent.document_id.in_(allowed_doc_ids),
                or_(
                    KgSourceEvent.title.ilike(pattern),
                    KgSourceEvent.summary.ilike(pattern),
                ),
            )
            .order_by(KgSourceEvent.updated_at.desc())
            .limit(remaining)
            .all()
        )
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


@router.get("/stats", response_model=KGStatsResponse)
async def get_kg_stats(
    document_ids: list[UUID] | None = Query(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Lightweight KG statistics for the current tenant.

    - Requires KG_ENABLED=true.
    - Enforces document-level access control.
    """
    _ensure_enabled()

    allowed_doc_ids = _resolve_allowed_documents(
        document_ids=document_ids,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    if not allowed_doc_ids:
        return KGStatsResponse(events=0, entities=0, links=0, entity_types=[], updated_at=None)

    from sqlalchemy import func

    from app.rag.kg.models import KgEntity, KgEventEntity, KgSourceEvent

    event_count = (
        db.query(func.count(KgSourceEvent.id))
        .filter(KgSourceEvent.tenant_id == tenant_id, KgSourceEvent.document_id.in_(allowed_doc_ids))
        .scalar()
        or 0
    )
    link_count = (
        db.query(func.count(KgEventEntity.id))
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(KgSourceEvent.tenant_id == tenant_id, KgSourceEvent.document_id.in_(allowed_doc_ids))
        .scalar()
        or 0
    )
    entity_count = (
        db.query(func.count(func.distinct(KgEventEntity.entity_id)))
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(KgSourceEvent.tenant_id == tenant_id, KgSourceEvent.document_id.in_(allowed_doc_ids))
        .scalar()
        or 0
    )
    updated_at = (
        db.query(func.max(KgSourceEvent.updated_at))
        .filter(KgSourceEvent.tenant_id == tenant_id, KgSourceEvent.document_id.in_(allowed_doc_ids))
        .scalar()
    )

    type_rows = (
        db.query(KgEntity.type, func.count(func.distinct(KgEntity.id)).label("cnt"))
        .join(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(KgSourceEvent.tenant_id == tenant_id, KgSourceEvent.document_id.in_(allowed_doc_ids))
        .group_by(KgEntity.type)
        .order_by(func.count(func.distinct(KgEntity.id)).desc(), KgEntity.type.asc())
        .limit(50)
        .all()
    )

    return KGStatsResponse(
        events=int(event_count),
        entities=int(entity_count),
        links=int(link_count),
        entity_types=[{"type": str(t or "unknown"), "count": int(cnt or 0)} for (t, cnt) in type_rows],
        updated_at=updated_at,
    )


@router.get("/graph/export")
async def export_kg_graph(
    document_ids: list[UUID] | None = Query(default=None),
    max_events: int = Query(default=200, ge=1, le=2000),
    max_entities: int = Query(default=400, ge=1, le=5000),
    max_links: int = Query(default=2000, ge=1, le=20000),
    include_entity_links: bool = Query(default=False, description="Include entity-entity co-occurrence links"),
    min_shared_events: int = Query(default=2, ge=1, le=100),
    max_entity_links: int = Query(default=1000, ge=0, le=20000),
    download: bool = Query(default=True),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Export KG graph projection as GraphML for external tooling.

    Uses the same access control and projection logic as `GET /kg/graph`.
    """
    graph = await get_kg_graph(
        document_ids=document_ids,
        max_events=max_events,
        max_entities=max_entities,
        max_links=max_links,
        include_entity_links=include_entity_links,
        min_shared_events=min_shared_events,
        max_entity_links=max_entity_links,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )

    import xml.etree.ElementTree as ET

    root = ET.Element("graphml", xmlns="http://graphml.graphdrawing.org/xmlns")

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
        headers["Content-Disposition"] = f'attachment; filename="mimirq-kg-{tenant_id}.graphml"'

    return Response(content=payload, media_type="application/graphml+xml", headers=headers)


@router.get("/events/{event_id}", response_model=KGEventDetailResponse)
async def get_kg_event_detail(
    event_id: UUID,
    document_ids: list[UUID] | None = Query(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Get a KG event with its linked entities (scoped to accessible documents)."""
    _ensure_enabled()

    allowed_doc_ids = _resolve_allowed_documents(
        document_ids=document_ids,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    if not allowed_doc_ids:
        raise HTTPException(status_code=404, detail="No accessible documents")

    from app.rag.kg.models import KgEntity, KgEventEntity, KgSourceEvent
    from app.rag.kg.provenance import build_event_entity_provenance

    ev = (
        db.query(KgSourceEvent)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.id == event_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
        )
        .first()
    )
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


@router.get("/entities/{entity_id}", response_model=KGEntityDetailResponse)
async def get_kg_entity_detail(
    entity_id: UUID,
    document_ids: list[UUID] | None = Query(default=None),
    max_events: int = Query(default=30, ge=1, le=200),
    max_neighbors: int = Query(default=20, ge=0, le=200),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Get a KG entity, its recent events, and co-occurring entity neighbors."""
    _ensure_enabled()

    allowed_doc_ids = _resolve_allowed_documents(
        document_ids=document_ids,
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
        raise HTTPException(status_code=404, detail="KG entity not found")

    total_events = (
        db.query(func.count(func.distinct(KgEventEntity.event_id)))
        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
            KgEventEntity.entity_id == entity_id,
        )
        .scalar()
        or 0
    )
    if not total_events:
        raise HTTPException(status_code=404, detail="KG entity not found")

    events = (
        db.query(KgSourceEvent)
        .join(KgEventEntity, KgEventEntity.event_id == KgSourceEvent.id)
        .filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.document_id.in_(allowed_doc_ids),
            KgEventEntity.entity_id == entity_id,
        )
        .order_by(desc(KgSourceEvent.updated_at))
        .limit(int(max_events))
        .all()
    )
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


@router.delete("/documents/{document_id}", response_model=KGDeleteResponse)
async def delete_kg_for_document(
    document_id: UUID,
    prune_orphan_entities: bool | None = Query(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Delete KG events for a document (and optionally prune orphan entities)."""
    _ensure_enabled()
    filter_allowed_document_ids(db, tenant_id, account_id, [document_id])

    eff_prune_orphans = bool(
        settings.KG_EXTRACT_PRUNE_ORPHAN_ENTITIES if prune_orphan_entities is None else prune_orphan_entities
    )

    from app.services.indexer import Indexer

    stats = Indexer(db).delete_event_indexes(
        tenant_id=tenant_id,
        document_id=document_id,
        prune_orphan_entities=eff_prune_orphans,
    )
    return KGDeleteResponse(document_id=document_id, **(stats or {}))


@router.post("/documents/{document_id}/extract", response_model=KGExtractResponse)
async def run_kg_extraction_for_document(
    document_id: UUID,
    response: Response,
    async_mode: bool = Query(default=False, alias="async"),
    replace_existing: bool | None = Query(default=None, description="Replace previously extracted events for this document"),
    prune_orphan_entities: bool | None = Query(default=None, description="Prune entities with no remaining event links"),
    prompt_template_id: UUID | None = Query(default=None),
    prompt_template_key: str | None = Query(default=None),
    prompt_ab_experiment_key: str | None = Query(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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

    # If async=true, enqueue KG extraction (default remains synchronous for compatibility).
    if bool(async_mode):
        if not bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
            raise HTTPException(status_code=400, detail="Task queue is disabled (TASK_QUEUE_ENABLED=false)")
        try:
            from app.tasks.queue import enqueue_kg_extraction

            pipeline_hash = (document.doc_metadata or {}).get("pipeline_hash") or "unknown"
            job_id = f"kg:{tenant_id}:{document_id}:{pipeline_hash}"
            task_id = await enqueue_kg_extraction(
                tenant_id=tenant_id,
                document_id=document_id,
                requested_by=account_id,
                job_id=job_id,
                replace_existing=eff_replace_existing,
                prune_orphan_entities=eff_prune_orphans,
            )
            if task_id:
                meta = dict(document.doc_metadata or {})
                meta["kg_task_id"] = task_id
                document.doc_metadata = meta
                db.commit()
                db.refresh(document)

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
            replace_existing=eff_replace_existing,
            prune_orphan_entities=eff_prune_orphans,
        )
    except ConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"KG extraction failed: {str(exc)[:200]}") from exc

    return KGExtractResponse(
        document_id=document_id,
        chunk_count=len(chunks),
        event_count=len(events),
    )


@router.post("/search", response_model=KGSearchResponse)
async def run_kg_search(
    payload: KGSearchRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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
            tenant_id=tenant_id,
            account_id=account_id,
            db=db,
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
