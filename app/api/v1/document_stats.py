from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentStats
from app.core.database import get_db
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.document import Document as DBDocument
from app.models.document import DocumentPermission
from app.services.dataset_service import DatasetService

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/stats", response_model=DocumentStats, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_document_stats(
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

    if dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
        query = query.filter(DBDocument.dataset_id == dataset_id)
    else:
        partial_member_subq = select(DatasetPermission.dataset_id).where(
            DatasetPermission.tenant_id == tenant_id,
            DatasetPermission.account_id == account_id,
        )

        allowed_dataset_filter = or_(
            Dataset.owner_id == account_id,
            Dataset.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS,
            and_(
                Dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS,
                Dataset.id.in_(partial_member_subq),
            ),
        )

        allowed_dataset_ids_subq = select(Dataset.id).where(
            Dataset.tenant_id == tenant_id,
            allowed_dataset_filter,
        )

        query = query.filter(
            or_(
                DBDocument.dataset_id.is_(None),
                DBDocument.dataset_id.in_(allowed_dataset_ids_subq),
            )
        )

    # Document-level ACL filter ("security trimming").
    doc_perm_subq = select(DocumentPermission.document_id).where(
        DocumentPermission.tenant_id == tenant_id,
        DocumentPermission.account_id == account_id,
    )
    owner_dataset_ids_subq = select(Dataset.id).where(
        Dataset.tenant_id == tenant_id,
        Dataset.owner_id == account_id,
    )
    query = query.filter(
        or_(
            DBDocument.dataset_id.in_(owner_dataset_ids_subq),
            DBDocument.access_mode.is_(None),
            DBDocument.access_mode.in_(["inherit", "all_team_members"]),
            DBDocument.owner_id == account_id,
            and_(DBDocument.access_mode == "partial_members", DBDocument.id.in_(doc_perm_subq)),
        )
    )

    lifecycle0 = str(lifecycle or "active").strip().lower()
    if lifecycle0 != "all":
        if lifecycle0 == "archived":
            query = query.filter(DBDocument.archived_at.isnot(None))
        elif lifecycle0 == "disabled":
            query = query.filter(DBDocument.disabled_at.isnot(None))
        else:
            query = query.filter(DBDocument.archived_at.is_(None), DBDocument.disabled_at.is_(None))

    if q:
        term = q.strip()
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

    status_rows = (
        query.with_entities(DBDocument.status, func.count(DBDocument.id))
        .group_by(DBDocument.status)
        .all()
    )
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
