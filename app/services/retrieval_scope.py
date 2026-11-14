"""Tenant and document scope for retrieval requests."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services import dataset_service
from app.services.document_access import (
    filter_allowed_document_ids,
    get_readable_datasets_map,
    list_accessible_document_ids,
)

DATASET_REQUIRED_WHEN_DOC_IDS_EMPTY_DETAIL = "dataset_id is required when document_ids is empty"
NO_ACCESSIBLE_DOCS_FOR_RETRIEVAL_DETAIL = "No accessible documents for retrieval"
DATASET_ID_AND_DATASET_IDS_CONFLICT_DETAIL = "dataset_id and dataset_ids are mutually exclusive"


def _unique_dataset_ids(dataset_ids: list[UUID] | None) -> list[UUID]:
    seen: set[UUID] = set()
    out: list[UUID] = []
    for dataset_id in dataset_ids or []:
        if dataset_id in seen:
            continue
        seen.add(dataset_id)
        out.append(dataset_id)
    return out


def _assert_dataset_ids_readable(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_ids: list[UUID],
) -> None:
    get_readable_datasets_map(db, tenant_id, account_id, dataset_ids, check_member=False)


def _enforce_non_empty_retrieval_scope(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    scope_document_ids: list[UUID] | None,
    scope_dataset_id: UUID | None,
    scope_dataset_ids: list[UUID] | None = None,
    allow_empty_scope: bool = False,
) -> None:
    dataset_ids = _unique_dataset_ids(scope_dataset_ids)
    if allow_empty_scope and bool(settings.CHAT_ALLOW_EMPTY_DOCUMENTS):
        return
    if bool(settings.CHAT_ALLOW_EMPTY_DOCUMENTS) and scope_dataset_id is None and not dataset_ids:
        return
    if scope_document_ids:
        return

    if scope_dataset_id is not None:
        from app.models.document import Document as DBDocument
        from app.services.dataset_profile_service import build_dataset_documents_query

        _ds, q = build_dataset_documents_query(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=scope_dataset_id,
        )
        q = q.filter(DBDocument.publication_status == "published")
        q = q.filter(
            (DBDocument.status == "completed") | (DBDocument.doc_metadata["active_pipeline_ready"].astext == "true")  # type: ignore[attr-defined]
        )
        exists = q.with_entities(DBDocument.id).order_by(DBDocument.updated_at.desc()).limit(1).first()
        if not exists:
            raise HTTPException(status_code=400, detail=NO_ACCESSIBLE_DOCS_FOR_RETRIEVAL_DETAIL)
        return

    if dataset_ids:
        from app.models.document import Document as DBDocument
        from app.services.dataset_profile_service import build_dataset_documents_query

        for dataset_id in dataset_ids:
            _ds, q = build_dataset_documents_query(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=dataset_id,
            )
            q = q.filter(DBDocument.publication_status == "published")
            q = q.filter(
                (DBDocument.status == "completed") | (DBDocument.doc_metadata["active_pipeline_ready"].astext == "true")  # type: ignore[attr-defined]
            )
            exists = q.with_entities(DBDocument.id).order_by(DBDocument.updated_at.desc()).limit(1).first()
            if exists:
                return
        raise HTTPException(status_code=400, detail=NO_ACCESSIBLE_DOCS_FOR_RETRIEVAL_DETAIL)

    exists = list_accessible_document_ids(db, tenant_id, account_id, status="completed", limit=1)
    if not exists:
        raise HTTPException(status_code=400, detail=NO_ACCESSIBLE_DOCS_FOR_RETRIEVAL_DETAIL)


def _resolve_retrieval_scope(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    document_ids: list[UUID],
    dataset_id: UUID | None,
    dataset_ids: list[UUID] | None = None,
    allow_multi_dataset: bool = False,
) -> tuple[UUID | None, list[UUID], list[UUID] | None]:
    requested_dataset_ids = _unique_dataset_ids(dataset_ids)
    if allow_multi_dataset and dataset_id is not None and requested_dataset_ids:
        raise HTTPException(status_code=400, detail=DATASET_ID_AND_DATASET_IDS_CONFLICT_DETAIL)

    scope_dataset_id: UUID | None = None
    scope_dataset_ids: list[UUID] = []
    scope_document_ids: list[UUID] | None = None
    if document_ids:
        scope_document_ids = filter_allowed_document_ids(db, tenant_id, account_id, document_ids)
    elif allow_multi_dataset and requested_dataset_ids:
        _assert_dataset_ids_readable(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_ids=requested_dataset_ids,
        )
        scope_dataset_ids = requested_dataset_ids
    elif dataset_id:
        ds = dataset_service.get_dataset(db, tenant_id, dataset_id)
        dataset_service.assert_dataset_readable(db, ds, account_id)
        scope_dataset_id = dataset_id
    elif not bool(settings.CHAT_ALLOW_OPEN_SCOPE):
        raise HTTPException(
            status_code=400,
            detail=DATASET_REQUIRED_WHEN_DOC_IDS_EMPTY_DETAIL,
        )

    _enforce_non_empty_retrieval_scope(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        scope_document_ids=scope_document_ids,
        scope_dataset_id=scope_dataset_id,
        scope_dataset_ids=scope_dataset_ids,
        allow_empty_scope=False,
    )
    return scope_dataset_id, scope_dataset_ids, scope_document_ids
