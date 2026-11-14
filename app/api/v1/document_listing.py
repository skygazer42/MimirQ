from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Query as ORMQuery
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import DocumentList, DocumentListQuery
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.models.document import Document
from app.services import dataset_service
from app.services.document_access import (
    apply_document_dataset_scope,
    apply_document_lifecycle_filter,
    build_document_read_filter,
)
from app.services.document_metadata_service import attach_runtime_document_metadata

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/", response_model=DocumentList)
def list_documents(
    params: Annotated[DocumentListQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentList:
    """
    List documents.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    query = db.query(Document).filter(Document.tenant_id == tenant_id)
    query = apply_document_dataset_scope(
        query=query,
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=params.dataset_id,
    )
    query = query.filter(build_document_read_filter(tenant_id=tenant_id, account_id=account_id))
    query = _apply_status_filter(query=query, status=params.status)
    query = apply_document_lifecycle_filter(query, params.lifecycle)
    if params.file_type:
        query = query.filter(Document.file_type == params.file_type)
    if params.owner_id:
        query = query.filter(Document.owner_id == params.owner_id)
    if params.q:
        query = query.filter(Document.filename.ilike(f"%{params.q}%"))
    if params.source_path_prefix:
        query = query.filter(Document.doc_metadata["source_path"].astext.startswith(params.source_path_prefix))

    total = query.count()
    order_columns = {
        "created_at": Document.created_at,
        "filename": Document.filename,
        "file_size": Document.file_size,
    }
    order_column = order_columns[params.order_by]
    query = query.order_by(order_column.asc() if params.order_dir == "asc" else order_column.desc(), Document.id.asc())
    documents = query.offset(params.skip).limit(params.limit).all()
    for document in documents:
        attach_runtime_document_metadata(document)
    return DocumentList(total=total, items=documents)


def _apply_status_filter(*, query: ORMQuery[Document], status: str | None) -> ORMQuery[Document]:
    if not status or status == "all":
        return query
    # Only the processing shortcut is normalized; other statuses match the raw value.
    if status.strip().lower() == "processing":
        return query.filter(Document.status.in_(["pending", "processing"]))
    return query.filter(Document.status == status)
