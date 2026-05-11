from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.services.document_access import list_accessible_document_ids


def enforce_non_empty_chat_scope(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    allowed_doc_ids: list[UUID],
    scope_dataset_id: UUID | None,
    error_detail: str,
) -> None:
    if allowed_doc_ids:
        return
    if scope_dataset_id is not None:
        from app.models.document import Document as DBDocument  # noqa: WPS433
        from app.services.dataset_profile_service import build_dataset_documents_query  # noqa: WPS433

        _, q = build_dataset_documents_query(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=scope_dataset_id,
        )
        q = q.filter(DBDocument.publication_status == "published")
        q = q.filter(
            (DBDocument.status == "completed")
            | (DBDocument.doc_metadata["active_pipeline_ready"].astext == "true")  # type: ignore[attr-defined]
        )
        if not q.with_entities(DBDocument.id).limit(1).first():
            raise HTTPException(status_code=400, detail=error_detail)
        return
    if not list_accessible_document_ids(db, tenant_id, account_id, status="completed", limit=1):
        raise HTTPException(status_code=400, detail=error_detail)
