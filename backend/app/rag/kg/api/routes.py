from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.models.document import Document as DBDocument, DocumentChunk
from app.rag.kg.schemas import KGExtractResponse, KGSearchRequest, KGSearchResponse, KGGraphNode, KGGraphResponse
from app.rag.kg.utils import get_logger
from app.services.document_access import filter_allowed_document_ids, list_accessible_document_ids
from app.services.dataset_service import DatasetService
from app.rag.kg.pipeline import extract_events, kg_search

router = APIRouter()
logger = get_logger("kg.api")

MAX_DOCUMENT_IDS = 500
MAX_GRAPH_SEARCH_QUERY_LEN = 200


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
    limit: int = 500,
) -> list[UUID]:
    if document_ids:
        # Avoid abuse: cap list size and dedupe while preserving input order.
        unique_ids = list(dict.fromkeys(document_ids))
        if limit and len(unique_ids) > int(limit):
            raise HTTPException(status_code=400, detail=f"Too many document_ids (max {int(limit)})")
        return filter_allowed_document_ids(db, tenant_id, account_id, unique_ids)
    return list_accessible_document_ids(db, tenant_id, account_id, status="completed", limit=limit)


def _build_graph_response(
    *,
    db: Session,
    tenant_id: UUID,
    events: list,
    max_entities: int,
    max_links: int,
    center_node_id: UUID | None = None,
    center_node_kind: str | None = None,
) -> KGGraphResponse:
    from collections import Counter

    from sqlalchemy import case, func

    from app.rag.kg.models import KgEntity, KgEventEntity

    if not events:
        stats = {"events": 0, "entities": 0, "links": 0}
        if center_node_id is not None:
            stats["center_node_id"] = str(center_node_id)
        return KGGraphResponse(nodes=[], links=[], stats=stats)

    event_ids = [e.id for e in events]

    forced_entity_id: UUID | None = center_node_id if center_node_kind == "entity" else None

    entity_counts = (
        db.query(KgEventEntity.entity_id, func.count(KgEventEntity.event_id))
        .join(KgEntity, KgEntity.id == KgEventEntity.entity_id)
        .filter(
            KgEventEntity.event_id.in_(event_ids),
            KgEntity.tenant_id == tenant_id,
        )
        .group_by(KgEventEntity.entity_id)
        .order_by(func.count(KgEventEntity.event_id).desc())
        .limit(int(max_entities))
        .all()
    )
    entity_ids = [row[0] for row in entity_counts]
    entity_hit_count: Counter[str] = Counter({str(eid): int(cnt) for eid, cnt in entity_counts})
    if forced_entity_id is not None and forced_entity_id not in entity_ids:
        if max_entities and len(entity_ids) >= int(max_entities):
            entity_ids[-1] = forced_entity_id
        else:
            entity_ids.append(forced_entity_id)
    if forced_entity_id is not None and str(forced_entity_id) not in entity_hit_count:
        cnt = (
            db.query(func.count(KgEventEntity.event_id))
            .filter(
                KgEventEntity.event_id.in_(event_ids),
                KgEventEntity.entity_id == forced_entity_id,
            )
            .scalar()
        )
        entity_hit_count[str(forced_entity_id)] = int(cnt or 0)

    nodes: list[dict] = []
    links: list[dict] = []
    entity_node_count = 0

    # Stable grouping by entity type for frontend coloring.
    type_to_group: dict[str, int] = {}
    next_group = 1

    def _group_for(entity_type: str) -> int:
        nonlocal next_group
        key = (entity_type or "unknown").strip().lower() or "unknown"
        if key not in type_to_group:
            type_to_group[key] = next_group
            next_group += 1
        return type_to_group[key]

    included_entity_ids: set[UUID] = set()
    event_degree: Counter[str] = Counter()

    entity_by_id: dict[UUID, KgEntity] = {}
    if entity_ids:
        entities = (
            db.query(KgEntity)
            .filter(
                KgEntity.tenant_id == tenant_id,
                KgEntity.id.in_(entity_ids),
            )
            .all()
        )
        entity_by_id = {ent.id: ent for ent in entities}

        associations = (
            db.query(KgEventEntity)
            .filter(
                KgEventEntity.event_id.in_(event_ids),
                KgEventEntity.entity_id.in_(entity_ids),
            )
            .order_by(
                *(
                    [case((KgEventEntity.event_id == center_node_id, 0), else_=1)]
                    if center_node_kind == "event" and center_node_id is not None
                    else []
                ),
                *(
                    [case((KgEventEntity.entity_id == center_node_id, 0), else_=1)]
                    if center_node_kind == "entity" and center_node_id is not None
                    else []
                ),
                KgEventEntity.weight.desc(),
                KgEventEntity.id.asc(),
            )
            .limit(int(max_links))
            .all()
        )

        included_entity_ids = {assoc.entity_id for assoc in associations}
        if forced_entity_id is not None:
            included_entity_ids.add(forced_entity_id)
        for assoc in associations:
            event_degree[str(assoc.event_id)] += 1

        for assoc in associations:
            ent = entity_by_id.get(assoc.entity_id)
            if not ent:
                continue
            links.append(
                {
                    "source": str(assoc.event_id),
                    "target": str(ent.id),
                    "label": (assoc.role or "").strip() or getattr(ent, "type", "") or "mentions",
                    "weight": float(getattr(assoc, "weight", 1.0) or 1.0),
                    "meta": {},
                }
            )

    # Event nodes
    for ev in events:
        ev_id = str(ev.id)
        meta = {
            "kind": "event",
            "document_id": str(ev.document_id) if ev.document_id else "",
            "chunk_id": str(ev.chunk_id) if ev.chunk_id else "",
        }
        if center_node_id is not None:
            meta["center"] = str(ev.id) == str(center_node_id)
        nodes.append(
            {
                "id": ev_id,
                "label": (ev.title or "").strip() or ev_id,
                "group": 0,
                "val": max(1, int(event_degree.get(ev_id, 0))),
                "meta": meta,
            }
        )

    # Entity nodes (ordered by hit count)
    ordered_entity_ids = entity_ids
    if forced_entity_id is not None and forced_entity_id in ordered_entity_ids:
        ordered_entity_ids = [forced_entity_id] + [eid for eid in ordered_entity_ids if eid != forced_entity_id]

    for ent_id in ordered_entity_ids:
        if ent_id not in included_entity_ids:
            continue
        ent = entity_by_id.get(ent_id)
        if not ent:
            continue
        meta = {
            "kind": "entity",
            "type": getattr(ent, "type", None),
            "normalized_name": getattr(ent, "normalized_name", None),
        }
        if center_node_id is not None:
            meta["center"] = str(ent.id) == str(center_node_id)
        nodes.append(
            {
                "id": str(ent.id),
                "label": (ent.name or "").strip() or str(ent.id),
                "group": _group_for(getattr(ent, "type", "") or "unknown"),
                "val": max(1, int(entity_hit_count.get(str(ent.id), 0))),
                "meta": meta,
            }
        )
        entity_node_count += 1

    stats = {
        "events": len(events),
        "entities": entity_node_count,
        "links": min(len(links), int(max_links)),
    }
    if center_node_id is not None:
        stats["center_node_id"] = str(center_node_id)

    return KGGraphResponse(nodes=nodes, links=links, stats=stats)


@router.get("/graph", response_model=KGGraphResponse)
async def get_kg_graph(
    document_ids: list[UUID] | None = Query(default=None),
    max_events: int = Query(default=200, ge=1, le=2000),
    max_entities: int = Query(default=400, ge=1, le=5000),
    max_links: int = Query(default=2000, ge=1, le=20000),
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
    DatasetService.ensure_member(db, tenant_id, account_id)

    allowed_doc_ids: list[UUID]
    allowed_doc_ids = _resolve_allowed_documents(
        document_ids=document_ids,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        limit=MAX_DOCUMENT_IDS,
    )

    if not allowed_doc_ids:
        return KGGraphResponse(nodes=[], links=[], stats={"reason": "no_accessible_documents"})

    from app.rag.kg.models import KgSourceEvent

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

    return _build_graph_response(
        db=db,
        tenant_id=tenant_id,
        events=events,
        max_entities=int(max_entities),
        max_links=int(max_links),
    )


@router.get("/graph/expand", response_model=KGGraphResponse)
async def expand_kg_graph(
    node_id: UUID = Query(..., description="Center node id (KgSourceEvent.id or KgEntity.id)"),
    document_ids: list[UUID] | None = Query(default=None),
    max_events: int = Query(default=50, ge=1, le=500),
    max_entities: int = Query(default=400, ge=1, le=5000),
    max_links: int = Query(default=5000, ge=1, le=20000),
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
    DatasetService.ensure_member(db, tenant_id, account_id)

    allowed_doc_ids = _resolve_allowed_documents(
        document_ids=document_ids,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        limit=MAX_DOCUMENT_IDS,
    )
    if not allowed_doc_ids:
        return KGGraphResponse(nodes=[], links=[], stats={"reason": "no_accessible_documents"})

    from app.rag.kg.models import KgEntity, KgEventEntity, KgSourceEvent

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

    center_kind = "event" if center_event else "entity"
    return _build_graph_response(
        db=db,
        tenant_id=tenant_id,
        events=events,
        max_entities=int(max_entities),
        max_links=int(max_links),
        center_node_id=node_id,
        center_node_kind=center_kind,
    )


@router.get("/graph/search", response_model=list[KGGraphNode])
async def search_kg_graph_nodes(
    q: str = Query(..., min_length=1, max_length=MAX_GRAPH_SEARCH_QUERY_LEN, description="Search query"),
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
    DatasetService.ensure_member(db, tenant_id, account_id)

    allowed_doc_ids = _resolve_allowed_documents(
        document_ids=document_ids,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        limit=MAX_DOCUMENT_IDS,
    )

    from sqlalchemy import or_

    from app.rag.kg.models import KgEntity, KgEventEntity, KgSourceEvent

    q_text = (q or "").strip()
    if not q_text:
        return []

    # Keep entity/event search consistent with other KG routes: if the user has no accessible
    # documents in scope, do not return any KG nodes.
    if not allowed_doc_ids:
        return []

    mode = (kind or "all").strip().lower()
    if mode not in {"all", "entity", "event"}:
        mode = "all"

    nodes: list[KGGraphNode] = []

    # Deterministic grouping for entities in this response.
    type_to_group: dict[str, int] = {}
    next_group = 1

    def _group_for(entity_type: str) -> int:
        nonlocal next_group
        key = (entity_type or "unknown").strip().lower() or "unknown"
        if key not in type_to_group:
            type_to_group[key] = next_group
            next_group += 1
        return type_to_group[key]

    pattern = f"%{q_text}%"

    if mode in {"all", "entity"}:
        ents = (
            db.query(KgEntity)
            .join(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
            .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
            .filter(KgEntity.tenant_id == tenant_id)
            .filter(KgSourceEvent.tenant_id == tenant_id)
            .filter(KgSourceEvent.document_id.in_(allowed_doc_ids))
            .filter(or_(KgEntity.name.ilike(pattern), KgEntity.normalized_name.ilike(pattern)))
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
                    group=_group_for(getattr(ent, "type", "") or "unknown"),
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


@router.post("/documents/{document_id}/extract", response_model=KGExtractResponse)
async def run_kg_extraction_for_document(
    document_id: UUID,
    response: Response,
    async_mode: bool = Query(default=False, alias="async"),
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
    DatasetService.ensure_member(db, tenant_id, account_id)

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

    if (getattr(document, "status", "") or "").lower() != "completed":
        raise HTTPException(status_code=400, detail="Document is not completed yet. Process it first.")

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

    # async=true：入队执行 KG 抽取（默认仍同步执行，保持兼容）
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
            )
            if not task_id:
                raise HTTPException(status_code=503, detail="Task queue unavailable")
            if task_id:
                meta = dict(document.doc_metadata or {})
                meta["kg_task_id"] = task_id
                document.doc_metadata = meta
                db.commit()
                db.refresh(document)

            response.status_code = 202
            if task_id:
                response.headers["X-Task-Id"] = str(task_id)
            return KGExtractResponse(
                document_id=document_id,
                chunk_count=len(chunks),
                event_count=0,
                message="KG extraction queued",
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Failed to enqueue KG extraction tenant_id=%s document_id=%s",
                str(tenant_id),
                str(document_id),
            )
            raise HTTPException(status_code=503, detail="Failed to enqueue KG extraction") from exc

    events = await extract_events(
        [c.id for c in chunks],
        tenant_id=tenant_id,
        chunks=chunks,
        prompt_template_id=eff_prompt_template_id,
        prompt_template_key=eff_prompt_template_key,
        prompt_ab_experiment_key=eff_prompt_ab_experiment_key,
        ab_user_key=account_id,
    )

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
    DatasetService.ensure_member(db, tenant_id, account_id)

    if payload.tenant_id and payload.tenant_id != tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id mismatch")

    if not payload.document_ids:
        raise HTTPException(status_code=400, detail="document_ids are required for KG search")

    doc_ids = list(dict.fromkeys(payload.document_ids))
    if len(doc_ids) > MAX_DOCUMENT_IDS:
        raise HTTPException(status_code=400, detail=f"Too many document_ids (max {MAX_DOCUMENT_IDS})")

    allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, doc_ids)

    try:
        result = await kg_search(
            query=payload.query,
            tenant_id=tenant_id,
            document_ids=allowed_doc_ids,
        )
    except Exception as exc:
        logger.exception("KG search failed tenant_id=%s account_id=%s", str(tenant_id), str(account_id))
        raise HTTPException(status_code=500, detail="KG search failed") from exc

    return KGSearchResponse(result=result, query=payload.query)
