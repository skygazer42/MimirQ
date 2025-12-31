from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.models.document import Document as DBDocument, DocumentChunk
from app.rag.kg.schemas import KGExtractResponse, KGSearchRequest, KGSearchResponse, KGGraphResponse
from app.services.document_access import filter_allowed_document_ids, list_accessible_document_ids
from app.services.dataset_service import DatasetService
from app.rag.kg.pipeline import extract_events, kg_search

router = APIRouter()


def _ensure_enabled():
    if not settings.KG_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="KG is disabled. Set KG_ENABLED=true in your environment to enable it.",
        )


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
    if document_ids:
        allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, document_ids)
    else:
        allowed_doc_ids = list_accessible_document_ids(db, tenant_id, account_id, status="completed", limit=500)

    if not allowed_doc_ids:
        return KGGraphResponse(nodes=[], links=[], stats={"reason": "no_accessible_documents"})

    from collections import Counter

    from app.rag.kg.models import KgEntity, KgEventEntity, KgSourceEvent

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

    # Fetch join rows in one pass (event_id -> entity details + edge metadata)
    rows = (
        db.query(KgEventEntity, KgEntity)
        .join(KgEntity, KgEntity.id == KgEventEntity.entity_id)
        .filter(KgEventEntity.event_id.in_(event_ids))
        .all()
    )

    entity_hit_count: Counter[str] = Counter()
    event_degree: Counter[str] = Counter()
    for assoc, ent in rows:
        eid = str(ent.id)
        entity_hit_count[eid] += 1
        event_degree[str(assoc.event_id)] += 1

    allowed_entity_ids = set(entity_hit_count.keys())
    if max_entities and len(allowed_entity_ids) > int(max_entities):
        allowed_entity_ids = {eid for (eid, _cnt) in entity_hit_count.most_common(int(max_entities))}

    # Deterministic grouping for entity types (for stable coloring on frontend).
    type_to_group: dict[str, int] = {}
    next_group = 1

    def _group_for(entity_type: str) -> int:
        nonlocal next_group
        key = (entity_type or "unknown").strip().lower() or "unknown"
        if key not in type_to_group:
            type_to_group[key] = next_group
            next_group += 1
        return type_to_group[key]

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
        if ent_id not in allowed_entity_ids:
            continue

        if ent_id not in seen_entities:
            seen_entities.add(ent_id)
            nodes.append(
                {
                    "id": ent_id,
                    "label": (ent.name or "").strip() or ent_id,
                    "group": _group_for(getattr(ent, "type", "") or "unknown"),
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

        links.append(
            {
                "source": str(assoc.event_id),
                "target": ent_id,
                "label": (assoc.role or "").strip() or getattr(ent, "type", "") or "mentions",
                "weight": float(getattr(assoc, "weight", 1.0) or 1.0),
                "meta": {},
            }
        )

    return KGGraphResponse(
        nodes=nodes,
        links=links,
        stats={
            "events": len(events),
            "entities": len(seen_entities),
            "links": min(len(links), int(max_links)),
        },
    )


@router.post("/documents/{document_id}/extract", response_model=KGExtractResponse)
async def run_kg_extraction_for_document(
    document_id: UUID,
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

    if not payload.document_ids:
        raise HTTPException(status_code=400, detail="document_ids are required for KG search")

    allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, payload.document_ids)

    try:
        result = await kg_search(
            query=payload.query,
            tenant_id=tenant_id,
            document_ids=allowed_doc_ids,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"KG search failed: {exc}") from exc

    return KGSearchResponse(result=result, query=payload.query)
