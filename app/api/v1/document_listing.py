from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentList
from app.core.database import get_db
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.services.dataset_service import DatasetService
from app.services.document_access import build_dataset_read_filter, build_document_read_filter
from app.services.document_runtime_metadata import attach_runtime_document_metadata

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


class ListDocumentsQueryFields:
    def __init__(
        self,
        skip: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
        status: Annotated[str | None, Query()] = None,
        lifecycle: Annotated[Literal["active", "archived", "disabled", "all"], Query()] = "active",
        dataset_id: Annotated[UUID | None, Query()] = None,
        file_type: Annotated[str | None, Query(max_length=20)] = None,
        owner_id: Annotated[str | None, Query(max_length=255)] = None,
        q: Annotated[str | None, Query(max_length=200)] = None,
        source_path_prefix: Annotated[str | None, Query(max_length=500)] = None,
        order_by: Annotated[Literal["created_at", "filename", "file_size"], Query()] = "created_at",
        order_dir: Annotated[Literal["asc", "desc"], Query()] = "desc",
    ) -> None:
        self.skip = skip
        self.limit = limit
        self.status = status
        self.lifecycle = lifecycle
        self.dataset_id = dataset_id
        self.file_type = file_type
        self.owner_id = owner_id
        self.q = q
        self.source_path_prefix = source_path_prefix
        self.order_by = order_by
        self.order_dir = order_dir


def _source_path_prefix_expr(prefix: str | None):  # noqa: ANN201
    """
    Build a SQLAlchemy filter expression for document.metadata.source_path prefix matching.

    Notes:
    - The source_path is optional and stored in JSONB metadata as a directory-preserving upload key.
    - Returns None when prefix is empty, so callers can keep query logic simple.
    """
    val = str(prefix or "").strip()
    if not val:
        return None
    if len(val) > 500:
        val = val[:500]
    return DBDocument.doc_metadata["source_path"].astext.startswith(val)  # type: ignore[attr-defined]


@router.get("/", response_model=DocumentList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_documents(
    params: Annotated[ListDocumentsQueryFields, Depends()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    List documents.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    skip = params.skip
    limit = params.limit
    status = params.status
    lifecycle = params.lifecycle
    dataset_id = params.dataset_id
    file_type = params.file_type
    owner_id = params.owner_id
    q = params.q
    source_path_prefix = params.source_path_prefix
    order_by = params.order_by
    order_dir = params.order_dir

    query = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id)

    if dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
        query = query.filter(DBDocument.dataset_id == dataset_id)
    else:
        allowed_dataset_ids_subq = select(Dataset.id).where(
            Dataset.tenant_id == tenant_id,
            build_dataset_read_filter(tenant_id=tenant_id, account_id=account_id),
        )

        query = query.filter(
            or_(
                DBDocument.dataset_id.is_(None),
                DBDocument.dataset_id.in_(allowed_dataset_ids_subq),
            )
        )

    query = query.filter(
        build_document_read_filter(tenant_id=tenant_id, account_id=account_id)
    )

    if status and status != "all":
        normalized = str(status).strip().lower()
        if normalized == "processing":
            query = query.filter(DBDocument.status.in_(["pending", "processing"]))
        else:
            query = query.filter(DBDocument.status == status)

    lifecycle0 = str(lifecycle or "active").strip().lower()
    if lifecycle0 != "all":
        if lifecycle0 == "archived":
            query = query.filter(DBDocument.archived_at.isnot(None))
        elif lifecycle0 == "disabled":
            query = query.filter(DBDocument.disabled_at.isnot(None))
        else:
            query = query.filter(DBDocument.archived_at.is_(None), DBDocument.disabled_at.is_(None))

    if file_type:
        file_type_norm = str(file_type or "").strip().lower()
        if file_type_norm:
            query = query.filter(DBDocument.file_type == file_type_norm)

    if owner_id:
        owner_id_norm = str(owner_id or "").strip()
        if owner_id_norm:
            query = query.filter(DBDocument.owner_id == owner_id_norm)

    if q:
        term = q.strip()
        if term:
            query = query.filter(DBDocument.filename.ilike(f"%{term}%"))

    sp_expr = _source_path_prefix_expr(source_path_prefix)
    if sp_expr is not None:
        query = query.filter(sp_expr)

    total = int(query.count())

    if order_by == "filename":
        order_col = DBDocument.filename
    elif order_by == "file_size":
        order_col = DBDocument.file_size
    else:
        order_col = DBDocument.created_at

    query = query.order_by(order_col.asc() if order_dir == "asc" else order_col.desc(), DBDocument.id.asc())
    documents = query.offset(skip).limit(limit).all()
    for document in documents:
        attach_runtime_document_metadata(document)

    return {
        "total": total,
        "items": documents,
    }
