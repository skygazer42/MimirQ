"""
Governance helper endpoints.

This is primarily used by the UI for rule-pack discovery and profile editors.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.rag.preprocessing.rule_packs import list_governance_rule_packs
from app.services.dataset_service import DatasetService

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


class GovernanceRulePackListResponse(BaseModel):
    items: list[str] = Field(default_factory=list)


@router.get("/rule-packs", response_model=GovernanceRulePackListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_rule_packs(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    return {"items": list_governance_rule_packs()}


class StaleDocumentItem(BaseModel):
    """
    PII-safe document row for lifecycle governance reporting.

    Intentionally excludes:
    - document content
    - chunk content
    - raw metadata blobs
    """

    id: UUID
    filename: str
    file_type: str
    status: str
    lifecycle_owner: str | None = None
    review_due_at: datetime | None = None
    authority_level: int | None = None
    supersedes_document_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StaleDocumentsByDatasetResponse(BaseModel):
    dataset_id: UUID
    as_of: datetime
    due_before: datetime
    mode: Literal["overdue", "due_soon", "all"]
    skip: int
    limit: int
    total: int
    items: list[StaleDocumentItem] = Field(default_factory=list)


@router.get(
    "/datasets/{dataset_id}/stale-documents",
    response_model=StaleDocumentsByDatasetResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def list_stale_documents_by_dataset(
    dataset_id: UUID,
    mode: Annotated[Literal["overdue", "due_soon", "all"], Query()] = "all",
    due_within_days: Annotated[
        int, Query(ge=0, le=365, description="Used for mode=due_soon/all when due_before is not set")
    ] = 7,
    due_before: Annotated[datetime | None, Query(description="Optional explicit upper bound for review_due_at")] = None,
    as_of: Annotated[datetime | None, Query(description="Optional reference time (defaults to now, UTC)")] = None,
    include_inactive: Annotated[bool, Query(description="Include archived/disabled documents")] = False,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    order_by: Annotated[
        Literal["review_due_at", "authority_level", "updated_at", "created_at", "filename"], Query()
    ] = "review_due_at",
    order_dir: Annotated[Literal["asc", "desc"], Query()] = "asc",
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    List documents with `review_due_at` due/overdue within a dataset (pagination + sort).

    RBAC: dataset editor/admin (dataset writable).
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    now = as_of or datetime.now(UTC)
    upper = due_before or (now + timedelta(days=int(due_within_days or 0)))

    q = (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
        )
        .filter(DBDocument.review_due_at.isnot(None))
    )

    if not include_inactive:
        q = q.filter(DBDocument.archived_at.is_(None), DBDocument.disabled_at.is_(None))

    mode0 = str(mode or "all").strip().lower()
    if mode0 == "overdue":
        q = q.filter(DBDocument.review_due_at <= now)
    elif mode0 == "due_soon":
        q = q.filter(DBDocument.review_due_at > now, DBDocument.review_due_at <= upper)
    else:
        q = q.filter(DBDocument.review_due_at <= upper)

    # Sorting (keep deterministic pagination by tying on id ASC).
    col = {
        "review_due_at": DBDocument.review_due_at,
        "authority_level": DBDocument.authority_level,
        "updated_at": DBDocument.updated_at,
        "created_at": DBDocument.created_at,
        "filename": DBDocument.filename,
    }.get(str(order_by or "review_due_at"), DBDocument.review_due_at)

    if str(order_dir or "asc").lower() == "desc":
        q = q.order_by(desc(col), asc(DBDocument.id))
    else:
        q = q.order_by(asc(col), asc(DBDocument.id))

    total = int(q.count() or 0)
    rows = q.offset(int(skip or 0)).limit(int(limit or 0)).all()

    items: list[StaleDocumentItem] = []
    for d in rows:
        items.append(
            StaleDocumentItem(
                id=d.id,
                filename=str(getattr(d, "filename", "") or ""),
                file_type=str(getattr(d, "file_type", "") or ""),
                status=str(getattr(d, "status", "") or ""),
                lifecycle_owner=getattr(d, "lifecycle_owner", None),
                review_due_at=getattr(d, "review_due_at", None),
                authority_level=getattr(d, "authority_level", None),
                supersedes_document_id=getattr(d, "supersedes_document_id", None),
                created_at=getattr(d, "created_at", None),
                updated_at=getattr(d, "updated_at", None),
            )
        )

    return StaleDocumentsByDatasetResponse(
        dataset_id=dataset_id,
        as_of=now,
        due_before=upper,
        mode=mode0 if mode0 in {"overdue", "due_soon", "all"} else "all",
        skip=int(skip or 0),
        limit=int(limit or 0),
        total=total,
        items=items,
    )
