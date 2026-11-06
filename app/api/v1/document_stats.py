from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Query as ORMQuery
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentStats
from app.api.utils.http_exception_responses import (
    DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.services import dataset_service
from app.services.document_access import (
    apply_document_dataset_scope,
    apply_document_lifecycle_filter,
    build_document_read_filter,
)

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/stats", response_model=DocumentStats, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_document_stats(
    dataset_id: UUID | None = None,
    lifecycle: Annotated[Literal["active", "archived", "disabled", "all"], Query()] = "active",
    file_type: Annotated[str | None, Query(max_length=20)] = None,
    owner_id: Annotated[str | None, Query(max_length=255)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int | dict[str, int]]:
    """
    Document stats for knowledge-base dashboards.

    Notes:
    - Enforces the same dataset permission semantics as `list_documents`.
    - Supports lightweight filename search via `q`.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)

    query = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id)
    query = apply_document_dataset_scope(
        query=query,
        dataset_id=dataset_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    query = query.filter(build_document_read_filter(tenant_id=tenant_id, account_id=account_id))
    query = apply_document_lifecycle_filter(query, lifecycle)
    query = _apply_document_stats_filters(
        query,
        filename_query=q,
        file_type=file_type,
        owner_id=owner_id,
    )

    status_rows = query.with_entities(DBDocument.status, func.count(DBDocument.id)).group_by(DBDocument.status).all()
    by_status = {status: count for status, count in status_rows}
    total = sum(by_status.values())

    sums = query.with_entities(
        func.coalesce(func.sum(DBDocument.chunk_count), 0),
        func.coalesce(func.sum(DBDocument.file_size), 0),
    ).one()
    total_chunks = int(sums[0])
    total_size = int(sums[1])

    return {
        "total": total,
        "by_status": by_status,
        "total_chunks": total_chunks,
        "total_size": total_size,
    }


def _apply_document_stats_filters(
    query: ORMQuery[DBDocument],
    *,
    filename_query: str | None,
    file_type: str | None,
    owner_id: str | None,
) -> ORMQuery[DBDocument]:
    if filename_query:
        term = filename_query.strip()
        if term:
            query = query.filter(DBDocument.filename.ilike(f"%{term}%"))

    if file_type:
        normalized_file_type = file_type.strip().lower()
        if normalized_file_type:
            query = query.filter(DBDocument.file_type == normalized_file_type)

    if owner_id:
        normalized_owner_id = owner_id.strip()
        if normalized_owner_id:
            query = query.filter(DBDocument.owner_id == normalized_owner_id)
    return query
