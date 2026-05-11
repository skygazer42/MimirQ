from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document_folders import DocumentFolderTreeResponse
from app.core.database import get_db
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.models.document import DocumentPermission
from app.services.dataset_service import DatasetService
from app.services.document_folders import build_document_folder_tree

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/folders", response_model=DocumentFolderTreeResponse)
async def list_document_folders(
    dataset_id: Annotated[UUID, Query(...)],
    lifecycle: Annotated[Literal["active", "archived", "disabled", "all"], Query()] = "active",
    max_depth: Annotated[int, Query(ge=1, le=50)] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Build a folder tree derived from `document.metadata.source_path`.

    Notes:
    - `source_path` is only present when the client uploads with directory-preserving keys.
    - The tree is dataset-scoped for performance and permission clarity.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    query = db.query(DBDocument).filter(
        DBDocument.tenant_id == tenant_id,
        DBDocument.dataset_id == dataset_id,
    )

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
            and_(
                DBDocument.access_mode == "partial_members",
                DBDocument.id.in_(doc_perm_subq),
            ),
        )
    )

    lifecycle0 = str(lifecycle or "active").strip().lower()
    if lifecycle0 != "all":
        if lifecycle0 == "archived":
            query = query.filter(DBDocument.archived_at.isnot(None))
        elif lifecycle0 == "disabled":
            query = query.filter(DBDocument.disabled_at.isnot(None))
        else:
            query = query.filter(
                DBDocument.archived_at.is_(None),
                DBDocument.disabled_at.is_(None),
            )

    total = int(query.count() or 0)

    rows = query.with_entities(DBDocument.doc_metadata["source_path"].astext).all()  # type: ignore[attr-defined]
    source_paths = [
        row[0]
        for row in rows
        if isinstance(row, tuple) and isinstance(row[0], str) and row[0].strip()
    ]

    root = build_document_folder_tree(
        source_paths,
        total_documents=total,
        max_depth=int(max_depth or 20),
    )
    return DocumentFolderTreeResponse(
        dataset_id=dataset_id,
        total_documents=total,
        total_with_source_path=len(source_paths),
        root=root,
    )
