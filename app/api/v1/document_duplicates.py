from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Row, func
from sqlalchemy.orm import Query as ORMQuery
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import (
    DocumentDuplicateGroup,
    DocumentDuplicateList,
    DocumentDuplicateQuery,
    DuplicateDocumentItem,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.models.document import Document
from app.services import dataset_service
from app.services.document_access import build_document_read_filter

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)

_DuplicateGroupRow = Row[tuple[str, int, datetime | None]]
_DuplicateDocumentRow = Row[tuple[str, UUID, str, str, UUID, datetime | None, int]]
_DuplicateScanRow = Row[tuple[UUID, str, str, UUID, datetime | None, object]]


@router.get("/duplicates", response_model=DocumentDuplicateList)
def list_document_duplicates(
    params: Annotated[DocumentDuplicateQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentDuplicateList:
    """
    Find duplicate documents by `documents.metadata.file_sha256` within a dataset.

    Notes:
    - Requires dataset read permission.
    - Applies document-level ACL filtering for non-owners ("security trimming").
    - Uses Postgres grouping when available to avoid loading all documents into memory.
    - Best-effort and bounded by `max_groups`/`max_docs_per_group`.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    dataset = dataset_service.get_dataset(db, tenant_id, params.dataset_id)
    dataset_service.assert_dataset_readable(db, dataset, account_id)
    base_query = db.query(Document).filter(
        Document.tenant_id == tenant_id,
        Document.dataset_id == params.dataset_id,
        build_document_read_filter(tenant_id=tenant_id, account_id=account_id),
    )
    if db.get_bind().dialect.name == "postgresql":
        return _list_document_duplicates_fast_path(base_query, params)
    return _list_document_duplicates_scan(base_query, params)


def _list_document_duplicates_fast_path(
    base_query: ORMQuery[Document], params: DocumentDuplicateQuery
) -> DocumentDuplicateList:
    db = base_query.session
    sha_expr = Document.doc_metadata["file_sha256"].astext
    sha_key_expr = func.lower(sha_expr)
    count_expr = func.count(Document.id)
    newest_expr = func.max(Document.created_at)
    group_query = (
        base_query.with_entities(sha_key_expr.label("sha"))
        .filter(sha_expr.isnot(None), sha_expr != "")
        .group_by(sha_key_expr)
        .having(count_expr >= params.min_count)
    )
    total_groups = db.query(func.count()).select_from(group_query.subquery()).scalar()
    top_groups: list[_DuplicateGroupRow] = (
        group_query.with_entities(sha_key_expr.label("sha"), count_expr.label("cnt"), newest_expr.label("newest_at"))
        .order_by(count_expr.desc(), newest_expr.desc(), sha_key_expr.asc())
        .limit(params.max_groups)
        .all()
    )
    groups = [(row.sha.strip().lower(), row.cnt) for row in top_groups]
    if not groups:
        return DocumentDuplicateList(total=total_groups)

    sha_list = [sha for sha, _count in groups]
    rownum = func.row_number().over(partition_by=sha_key_expr, order_by=Document.created_at.desc()).label("rn")
    docs_subquery = (
        base_query.with_entities(
            sha_key_expr.label("sha"),
            Document.id.label("id"),
            Document.filename.label("filename"),
            Document.status.label("status"),
            Document.dataset_id.label("dataset_id"),
            Document.created_at.label("created_at"),
            rownum,
        )
        .filter(sha_key_expr.in_(sha_list))
        .subquery()
    )
    rows: list[_DuplicateDocumentRow] = (
        db.query(docs_subquery)
        .filter(docs_subquery.c.rn <= params.max_docs_per_group)
        .order_by(docs_subquery.c.sha.asc(), docs_subquery.c.created_at.desc())
        .all()
    )
    docs_by_sha: dict[str, list[_DuplicateDocumentRow]] = {}
    for row in rows:
        sha = row.sha.strip().lower()
        if sha:
            docs_by_sha.setdefault(sha, []).append(row)
    items = [
        DocumentDuplicateGroup(
            file_sha256=sha,
            count=count,
            documents=[
                DuplicateDocumentItem.model_validate(row, from_attributes=True)
                for row in docs_by_sha.get(sha, [])[: params.max_docs_per_group]
            ],
        )
        for sha, count in groups
        if sha
    ]
    return DocumentDuplicateList(total=total_groups, items=items)


def _created_at_timestamp(value: datetime | None) -> float:
    try:
        return value.timestamp() if value is not None else 0.0
    except (ValueError, OverflowError, OSError):
        return 0.0


def _list_document_duplicates_scan(
    base_query: ORMQuery[Document], params: DocumentDuplicateQuery
) -> DocumentDuplicateList:
    rows: list[_DuplicateScanRow] = base_query.with_entities(
        Document.id,
        Document.filename,
        Document.status,
        Document.dataset_id,
        Document.created_at,
        Document.doc_metadata,
    ).all()
    docs_by_sha: dict[str, list[_DuplicateScanRow]] = {}
    for row in rows:
        metadata = row.doc_metadata
        if not isinstance(metadata, dict):
            continue
        sha = metadata.get("file_sha256")
        if sha is None:
            continue
        sha = sha.strip().lower()
        if sha:
            docs_by_sha.setdefault(sha, []).append(row)

    groups = {sha: docs for sha, docs in docs_by_sha.items() if len(docs) >= params.min_count}
    sha_order = sorted(
        groups,
        key=lambda sha: (
            -len(groups[sha]),
            -max(_created_at_timestamp(row.created_at) for row in groups[sha]),
            sha,
        ),
    )
    items = []
    for sha in sha_order[: params.max_groups]:
        docs = groups[sha]
        docs_sorted = sorted(docs, key=lambda row: _created_at_timestamp(row.created_at), reverse=True)
        items.append(
            DocumentDuplicateGroup(
                file_sha256=sha,
                count=len(docs),
                documents=[
                    DuplicateDocumentItem.model_validate(row, from_attributes=True)
                    for row in docs_sorted[: params.max_docs_per_group]
                ],
            )
        )
    return DocumentDuplicateList(total=len(groups), items=items)
