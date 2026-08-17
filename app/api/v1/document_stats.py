from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentStats
from app.api.utils.http_exception_responses import (
    DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
from app.core.database import get_db
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.services.dataset_service import DatasetService
from app.services.document_access import build_dataset_read_filter, build_document_read_filter

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
):
    """
    Document stats for knowledge-base dashboards.

    Notes:
    - Enforces the same dataset permission semantics as `list_documents`.
    - Supports lightweight filename search via `q`.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id)
    query = _apply_document_stats_dataset_scope(
        query,
        dataset_id=dataset_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    query = query.filter(build_document_read_filter(tenant_id=tenant_id, account_id=account_id))
    query = _apply_document_stats_lifecycle(query, lifecycle)
    query = _apply_document_stats_filters(
        query,
        filename_query=q,
        file_type=file_type,
        owner_id=owner_id,
    )

    status_rows = query.with_entities(DBDocument.status, func.count(DBDocument.id)).group_by(DBDocument.status).all()
    by_status = {str(status): int(count) for status, count in status_rows if status is not None}
    total = int(sum(by_status.values()))

    sums = query.with_entities(
        func.coalesce(func.sum(DBDocument.chunk_count), 0),
        func.coalesce(func.sum(DBDocument.file_size), 0),
    ).one()
    total_chunks = int(sums[0] or 0)
    total_size = int(sums[1] or 0)

    return {
        "total": total,
        "by_status": by_status,
        "total_chunks": total_chunks,
        "total_size": total_size,
    }


def _apply_document_stats_dataset_scope(
    query,
    *,
    dataset_id: UUID | None,
    tenant_id: UUID,
    account_id: str,
    db: Session,
):
    if dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
        return query.filter(DBDocument.dataset_id == dataset_id)

    allowed_dataset_ids_subquery = select(Dataset.id).where(
        Dataset.tenant_id == tenant_id,
        build_dataset_read_filter(tenant_id=tenant_id, account_id=account_id),
    )
    return query.filter(
        or_(
            DBDocument.dataset_id.is_(None),
            DBDocument.dataset_id.in_(allowed_dataset_ids_subquery),
        )
    )


def _apply_document_stats_lifecycle(query, lifecycle: str):
    normalized = str(lifecycle or "active").strip().lower()
    if normalized == "all":
        return query
    if normalized == "archived":
        return query.filter(DBDocument.archived_at.isnot(None))
    if normalized == "disabled":
        return query.filter(DBDocument.disabled_at.isnot(None))
    return query.filter(DBDocument.archived_at.is_(None), DBDocument.disabled_at.is_(None))


def _apply_document_stats_filters(
    query,
    *,
    filename_query: str | None,
    file_type: str | None,
    owner_id: str | None,
):
    if filename_query:
        term = filename_query.strip()
        if term:
            query = query.filter(DBDocument.filename.ilike(f"%{term}%"))

    if file_type:
        ft = str(file_type or "").strip().lower()
        if ft:
            query = query.filter(DBDocument.file_type == ft)

    if owner_id:
        oid = str(owner_id or "").strip()
        if oid:
            query = query.filter(DBDocument.owner_id == oid)
    return query
