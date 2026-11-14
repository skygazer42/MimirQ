from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import DocumentStats, DocumentStatsQuery
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.models.document import Document
from app.services import dataset_service
from app.services.document_access import (
    apply_document_dataset_scope,
    apply_document_lifecycle_filter,
    build_document_read_filter,
)

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/stats", response_model=DocumentStats)
def get_document_stats(
    params: Annotated[DocumentStatsQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentStats:
    """
    Document stats for knowledge-base dashboards.

    Notes:
    - Enforces the same dataset permission semantics as `list_documents`.
    - Supports lightweight filename search via `q`.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    query = db.query(Document).filter(Document.tenant_id == tenant_id)
    query = apply_document_dataset_scope(
        query=query,
        dataset_id=params.dataset_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    query = query.filter(build_document_read_filter(tenant_id=tenant_id, account_id=account_id))
    query = apply_document_lifecycle_filter(query, params.lifecycle)
    if params.q:
        query = query.filter(Document.filename.ilike(f"%{params.q}%"))
    if params.file_type:
        query = query.filter(Document.file_type == params.file_type)
    if params.owner_id:
        query = query.filter(Document.owner_id == params.owner_id)

    status_rows = query.with_entities(Document.status, func.count(Document.id)).group_by(Document.status).all()
    by_status = dict(status_rows)
    totals = query.with_entities(
        func.coalesce(func.sum(Document.chunk_count), 0).label("total_chunks"),
        func.coalesce(func.sum(Document.file_size), 0).label("total_size"),
    ).one()
    return DocumentStats(
        total=sum(by_status.values()),
        by_status=by_status,
        total_chunks=int(totals.total_chunks),
        total_size=int(totals.total_size),
    )
