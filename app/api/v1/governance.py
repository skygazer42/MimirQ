"""
Governance helper endpoints.

This is primarily used by the UI for rule-pack discovery and profile editors.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.pipelines import (
    GovernanceRulePackListResponse,
    StaleDocumentItem,
    StaleDocumentsByDatasetResponse,
    StaleDocumentsQuery,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.models.document import Document
from app.rag.preprocessing.rule_packs import list_governance_rule_packs
from app.services import dataset_service

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/rule-packs", response_model=GovernanceRulePackListResponse)
def list_rule_packs(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> GovernanceRulePackListResponse:
    dataset_service.ensure_member(db, tenant_id, account_id)
    return GovernanceRulePackListResponse(items=list_governance_rule_packs())


@router.get(
    "/datasets/{dataset_id}/stale-documents",
    response_model=StaleDocumentsByDatasetResponse,
)
def list_stale_documents_by_dataset(
    dataset_id: UUID,
    params: Annotated[StaleDocumentsQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> StaleDocumentsByDatasetResponse:
    """
    List documents with `review_due_at` due/overdue within a dataset (pagination + sort).

    RBAC: dataset editor/admin (dataset writable).
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    dataset = dataset_service.get_dataset(db, tenant_id, dataset_id)
    dataset_service.assert_dataset_writable(db, dataset, account_id)

    now = params.as_of if params.as_of is not None else datetime.now(UTC)
    upper = params.due_before if params.due_before is not None else now + timedelta(days=params.due_within_days)

    q = (
        db.query(Document)
        .filter(
            Document.tenant_id == tenant_id,
            Document.dataset_id == dataset_id,
        )
        .filter(Document.review_due_at.isnot(None))
    )

    if not params.include_inactive:
        q = q.filter(Document.archived_at.is_(None), Document.disabled_at.is_(None))

    if params.mode == "overdue":
        q = q.filter(Document.review_due_at <= now)
    elif params.mode == "due_soon":
        q = q.filter(Document.review_due_at > now, Document.review_due_at <= upper)
    else:
        q = q.filter(Document.review_due_at <= upper)

    # Sorting (keep deterministic pagination by tying on id ASC).
    col = {
        "review_due_at": Document.review_due_at,
        "authority_level": Document.authority_level,
        "updated_at": Document.updated_at,
        "created_at": Document.created_at,
        "filename": Document.filename,
    }[params.order_by]

    if params.order_dir == "desc":
        q = q.order_by(desc(col), asc(Document.id))
    else:
        q = q.order_by(asc(col), asc(Document.id))

    total = q.count()
    rows = q.offset(params.skip).limit(params.limit).all()

    items: list[StaleDocumentItem] = []
    for document in rows:
        items.append(
            StaleDocumentItem(
                id=document.id,
                filename=document.filename,
                file_type=document.file_type,
                status=document.status,
                lifecycle_owner=document.lifecycle_owner,
                review_due_at=document.review_due_at,
                authority_level=document.authority_level,
                supersedes_document_id=document.supersedes_document_id,
                created_at=document.created_at,
                updated_at=document.updated_at,
            )
        )

    return StaleDocumentsByDatasetResponse(
        dataset_id=dataset_id,
        as_of=now,
        due_before=upper,
        mode=params.mode,
        skip=params.skip,
        limit=params.limit,
        total=total,
        items=items,
    )
