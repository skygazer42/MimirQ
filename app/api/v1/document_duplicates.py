
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentDuplicateList
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.rag.core.logging import get_logger
from app.services.dataset_service import DatasetService
from app.services.document_access import build_document_read_filter

logger = get_logger(__name__)

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _resolve_sha_expressions() -> tuple[Any | None, Any | None]:
    try:
        sha_expr = DBDocument.doc_metadata["file_sha256"].astext  # type: ignore[attr-defined]
        return sha_expr, func.lower(sha_expr)
    except Exception:
        return None, None


def _build_duplicate_base_query(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    account_id: str,
):
    base_query = db.query(DBDocument).filter(
        DBDocument.tenant_id == tenant_id,
        DBDocument.dataset_id == dataset_id,
    )
    document_read_filter = build_document_read_filter(tenant_id=tenant_id, account_id=account_id)
    return base_query.filter(document_read_filter), document_read_filter


def _build_duplicate_doc_entry(
    *,
    doc_id: Any,
    filename: Any,
    status: Any,
    dataset_id: Any,
    created_at: Any,
) -> dict[str, Any]:
    return {
        "id": doc_id,
        "filename": filename,
        "status": str(status or ""),
        "dataset_id": dataset_id,
        "created_at": created_at,
    }


def _append_duplicate_docs(rows: list[Any]) -> dict[str, list[dict[str, Any]]]:
    docs_by_sha: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        sha = str(getattr(row, "sha", "") or "").strip().lower()
        if not sha:
            continue
        docs_by_sha.setdefault(sha, []).append(
            _build_duplicate_doc_entry(
                doc_id=row.id,
                filename=row.filename,
                status=row.status,
                dataset_id=row.dataset_id,
                created_at=row.created_at,
            )
        )
    return docs_by_sha


def _build_fast_duplicate_response(
    *,
    top_groups: list[Any],
    rows: list[Any],
    max_docs_per_group: int,
    total_groups: int,
) -> dict[str, Any]:
    docs_by_sha = _append_duplicate_docs(rows)
    items: list[dict[str, Any]] = []
    for row in top_groups:
        sha = str(row.sha or "").strip().lower()
        if not sha:
            continue
        items.append(
            {
                "file_sha256": sha,
                "count": int(row.cnt or 0),
                "documents": docs_by_sha.get(sha, [])[:max_docs_per_group],
            }
        )
    return {"total": total_groups, "items": items}


def _list_document_duplicates_fast_path(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    document_read_filter: Any,
    min_count: int,
    max_groups: int,
    max_docs_per_group: int,
    sha_expr: Any,
    sha_key_expr: Any,
) -> dict[str, Any]:
    group_all_q = (
        db.query(sha_key_expr.label("sha"))
        .select_from(DBDocument)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.dataset_id == dataset_id)
    )
    group_all_q = group_all_q.filter(document_read_filter)
    group_all_q = group_all_q.filter(sha_expr.isnot(None), sha_expr != "").group_by(sha_key_expr).having(
        func.count(DBDocument.id) >= min_count
    )
    total_groups = int(db.query(func.count()).select_from(group_all_q.subquery()).scalar() or 0)

    group_top_q = (
        db.query(
            sha_key_expr.label("sha"),
            func.count(DBDocument.id).label("cnt"),
            func.max(DBDocument.created_at).label("newest_at"),
        )
        .select_from(DBDocument)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.dataset_id == dataset_id)
    )
    group_top_q = group_top_q.filter(document_read_filter)
    group_top_q = (
        group_top_q.filter(sha_expr.isnot(None), sha_expr != "")
        .group_by(sha_key_expr)
        .having(func.count(DBDocument.id) >= min_count)
        .order_by(func.count(DBDocument.id).desc(), func.max(DBDocument.created_at).desc(), sha_key_expr.asc())
        .limit(max_groups)
    )
    top_groups = group_top_q.all()
    sha_list = [str(row.sha).strip().lower() for row in top_groups if row and row.sha]
    if not sha_list:
        return {"total": total_groups, "items": []}

    rownum = func.row_number().over(partition_by=sha_key_expr, order_by=DBDocument.created_at.desc()).label("rn")
    docs_q = (
        db.query(
            sha_key_expr.label("sha"),
            DBDocument.id.label("id"),
            DBDocument.filename.label("filename"),
            DBDocument.status.label("status"),
            DBDocument.dataset_id.label("dataset_id"),
            DBDocument.created_at.label("created_at"),
            rownum,
        )
        .select_from(DBDocument)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.dataset_id == dataset_id, sha_key_expr.in_(sha_list))
    )
    docs_q = docs_q.filter(document_read_filter)
    docs_subq = docs_q.subquery()
    rows = (
        db.query(docs_subq)
        .filter(docs_subq.c.rn <= max_docs_per_group)
        .order_by(docs_subq.c.sha.asc(), docs_subq.c.created_at.desc())
        .all()
    )
    return _build_fast_duplicate_response(
        top_groups=top_groups,
        rows=rows,
        max_docs_per_group=max_docs_per_group,
        total_groups=total_groups,
    )


def _dt_ts(value: Any) -> float:
    try:
        return float(value.timestamp()) if value is not None else 0.0
    except Exception:
        return 0.0


def _build_scan_duplicate_groups(
    rows: list[tuple[Any, Any, Any, Any, Any, Any]],
    *,
    min_count: int,
) -> list[tuple[str, list[dict[str, Any]], float]]:
    by_sha: dict[str, list[dict[str, Any]]] = {}
    for doc_id, filename, status, dataset_id, created_at, meta in rows:
        metadata = meta if isinstance(meta, dict) else {}
        sha = str(metadata.get("file_sha256") or "").strip().lower()
        if not sha:
            continue
        by_sha.setdefault(sha, []).append(
            _build_duplicate_doc_entry(
                doc_id=doc_id,
                filename=filename,
                status=status,
                dataset_id=dataset_id,
                created_at=created_at,
            )
        )

    groups_all: list[tuple[str, list[dict[str, Any]], float]] = []
    for sha, docs in by_sha.items():
        if len(docs) < min_count:
            continue
        newest_ts = max((_dt_ts(doc.get("created_at")) for doc in docs), default=0.0)
        groups_all.append((sha, docs, newest_ts))
    return groups_all


def _list_document_duplicates_scan(
    *,
    base_query: Any,
    min_count: int,
    max_groups: int,
    max_docs_per_group: int,
) -> dict[str, Any]:
    rows = base_query.with_entities(
        DBDocument.id,
        DBDocument.filename,
        DBDocument.status,
        DBDocument.dataset_id,
        DBDocument.created_at,
        DBDocument.doc_metadata,
    ).all()
    groups_all = _build_scan_duplicate_groups(rows, min_count=min_count)
    total_groups = len(groups_all)
    groups_all.sort(key=lambda item: (-len(item[1]), -float(item[2] or 0.0), item[0]))

    items: list[dict[str, Any]] = []
    for sha, docs, _newest_ts in groups_all[:max_groups]:
        docs_sorted = sorted(docs, key=lambda doc: _dt_ts(doc.get("created_at")), reverse=True)
        items.append(
            {
                "file_sha256": sha,
                "count": len(docs),
                "documents": docs_sorted[:max_docs_per_group],
            }
        )
    return {"total": total_groups, "items": items}


@router.get("/duplicates", response_model=DocumentDuplicateList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_document_duplicates(
    dataset_id: Annotated[UUID, Query(..., description="Dataset scope for duplicate detection")],
    min_count: Annotated[int, Query(ge=2, le=50)] = 2,
    max_groups: Annotated[int, Query(ge=1, le=200)] = 50,
    max_docs_per_group: Annotated[int, Query(ge=1, le=100)] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Find duplicate documents by `documents.metadata.file_sha256` within a dataset.

    Notes:
    - Requires dataset read permission.
    - Applies document-level ACL filtering for non-owners ("security trimming").
    - Uses Postgres grouping when available to avoid loading all documents into memory.
    - Best-effort and bounded by `max_groups`/`max_docs_per_group`.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    min_count_value = int(min_count or 2)
    max_groups_value = int(max_groups or 50)
    max_docs_per_group_value = int(max_docs_per_group or 20)
    sha_expr, sha_key_expr = _resolve_sha_expressions()
    base_query, document_read_filter = _build_duplicate_base_query(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        account_id=account_id,
    )

    # Fast path: Postgres group-by on JSONB metadata.
    if sha_expr is not None and sha_key_expr is not None:
        try:
            return _list_document_duplicates_fast_path(
                db=db,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                document_read_filter=document_read_filter,
                min_count=min_count_value,
                max_groups=max_groups_value,
                max_docs_per_group=max_docs_per_group_value,
                sha_expr=sha_expr,
                sha_key_expr=sha_key_expr,
            )
        except Exception as exc:
            # Fall back to the Python scan path below (best-effort).
            logger.debug("Postgres duplicate-document query failed; falling back to Python scan: %s", exc)
    return _list_document_duplicates_scan(
        base_query=base_query,
        min_count=min_count_value,
        max_groups=max_groups_value,
        max_docs_per_group=max_docs_per_group_value,
    )
