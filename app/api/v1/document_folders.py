from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import DocumentFolderQuery, DocumentFolderTreeResponse
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.models.document import Document
from app.services import dataset_service
from app.services.document_access import apply_document_lifecycle_filter, build_document_read_filter
from app.services.document_folders import build_document_folder_tree

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/folders", response_model=DocumentFolderTreeResponse)
def list_document_folders(
    params: Annotated[DocumentFolderQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentFolderTreeResponse:
    """
    Build a folder tree derived from `document.metadata.source_path`.

    Notes:
    - `source_path` is only present when the client uploads with directory-preserving keys.
    - The tree is dataset-scoped for performance and permission clarity.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)

    dataset = dataset_service.get_dataset(db, tenant_id, params.dataset_id)
    dataset_service.assert_dataset_readable(db, dataset, account_id)

    query = db.query(Document).filter(
        Document.tenant_id == tenant_id,
        Document.dataset_id == params.dataset_id,
        build_document_read_filter(tenant_id=tenant_id, account_id=account_id),
    )
    query = apply_document_lifecycle_filter(query, params.lifecycle)
    total = query.count()

    rows = query.with_entities(Document.doc_metadata["source_path"].astext).all()
    source_paths = [source_path for (source_path,) in rows if source_path is not None and source_path.strip()]

    root = build_document_folder_tree(
        source_paths,
        total_documents=total,
        max_depth=params.max_depth,
    )
    return DocumentFolderTreeResponse(
        dataset_id=params.dataset_id,
        total_documents=total,
        total_with_source_path=len(source_paths),
        root=root,
    )
