from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentDuplicateList
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.models.document import DocumentPermission
from app.services.dataset_service import DatasetService

logger = logging.getLogger(__name__)

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/duplicates", response_model=DocumentDuplicateList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def list_document_duplicates(
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

    sha_expr = None
    sha_key_expr = None
    try:
        sha_expr = DBDocument.doc_metadata["file_sha256"].astext  # type: ignore[attr-defined]
        sha_key_expr = func.lower(sha_expr)
    except Exception:
        sha_expr = None
        sha_key_expr = None

    base_query = db.query(DBDocument).filter(
        DBDocument.tenant_id == tenant_id,
        DBDocument.dataset_id == dataset_id,
    )

    # Document-level ACL filter (dataset owner bypass).
    if str(getattr(ds, "owner_id", "") or "") != str(account_id or ""):
        doc_perm_subq = (
            db.query(DocumentPermission.document_id)
            .filter(
                DocumentPermission.tenant_id == tenant_id,
                DocumentPermission.account_id == account_id,
            )
            .subquery()
        )
        base_query = base_query.filter(
            or_(
                DBDocument.access_mode.is_(None),
                DBDocument.access_mode.in_(["inherit", "all_team_members"]),
                DBDocument.owner_id == account_id,
                and_(
                    DBDocument.access_mode == "partial_members",
                    DBDocument.id.in_(doc_perm_subq),
                ),
            )
        )

    # Fast path: Postgres group-by on JSONB metadata.
    if sha_expr is not None and sha_key_expr is not None:
        try:
            # Total groups (count of distinct sha groups that meet min_count).
            group_all_q = (
                db.query(sha_key_expr.label("sha"))
                .select_from(DBDocument)
                .filter(DBDocument.tenant_id == tenant_id, DBDocument.dataset_id == dataset_id)
            )
            if str(getattr(ds, "owner_id", "") or "") != str(account_id or ""):
                doc_perm_subq = (
                    db.query(DocumentPermission.document_id)
                    .filter(
                        DocumentPermission.tenant_id == tenant_id,
                        DocumentPermission.account_id == account_id,
                    )
                    .subquery()
                )
                group_all_q = group_all_q.filter(
                    or_(
                        DBDocument.access_mode.is_(None),
                        DBDocument.access_mode.in_(["inherit", "all_team_members"]),
                        DBDocument.owner_id == account_id,
                        and_(
                            DBDocument.access_mode == "partial_members",
                            DBDocument.id.in_(doc_perm_subq),
                        ),
                    )
                )

            group_all_q = group_all_q.filter(sha_expr.isnot(None), sha_expr != "").group_by(sha_key_expr).having(
                func.count(DBDocument.id) >= int(min_count or 2)
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
            if str(getattr(ds, "owner_id", "") or "") != str(account_id or ""):
                doc_perm_subq = (
                    db.query(DocumentPermission.document_id)
                    .filter(
                        DocumentPermission.tenant_id == tenant_id,
                        DocumentPermission.account_id == account_id,
                    )
                    .subquery()
                )
                group_top_q = group_top_q.filter(
                    or_(
                        DBDocument.access_mode.is_(None),
                        DBDocument.access_mode.in_(["inherit", "all_team_members"]),
                        DBDocument.owner_id == account_id,
                        and_(
                            DBDocument.access_mode == "partial_members",
                            DBDocument.id.in_(doc_perm_subq),
                        ),
                    )
                )

            group_top_q = (
                group_top_q.filter(sha_expr.isnot(None), sha_expr != "")
                .group_by(sha_key_expr)
                .having(func.count(DBDocument.id) >= int(min_count or 2))
                .order_by(func.count(DBDocument.id).desc(), func.max(DBDocument.created_at).desc(), sha_key_expr.asc())
                .limit(int(max_groups or 50))
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
            if str(getattr(ds, "owner_id", "") or "") != str(account_id or ""):
                doc_perm_subq = (
                    db.query(DocumentPermission.document_id)
                    .filter(
                        DocumentPermission.tenant_id == tenant_id,
                        DocumentPermission.account_id == account_id,
                    )
                    .subquery()
                )
                docs_q = docs_q.filter(
                    or_(
                        DBDocument.access_mode.is_(None),
                        DBDocument.access_mode.in_(["inherit", "all_team_members"]),
                        DBDocument.owner_id == account_id,
                        and_(
                            DBDocument.access_mode == "partial_members",
                            DBDocument.id.in_(doc_perm_subq),
                        ),
                    )
                )

            docs_subq = docs_q.subquery()
            rows = (
                db.query(docs_subq)
                .filter(docs_subq.c.rn <= int(max_docs_per_group or 20))
                .order_by(docs_subq.c.sha.asc(), docs_subq.c.created_at.desc())
                .all()
            )

            docs_by_sha: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                sha = str(getattr(row, "sha", "") or "").strip().lower()
                if not sha:
                    continue
                docs_by_sha.setdefault(sha, []).append(
                    {
                        "id": row.id,
                        "filename": row.filename,
                        "status": str(row.status or ""),
                        "dataset_id": row.dataset_id,
                        "created_at": row.created_at,
                    }
                )

            items: list[dict[str, Any]] = []
            for row in top_groups:
                sha = str(row.sha or "").strip().lower()
                if not sha:
                    continue
                items.append(
                    {
                        "file_sha256": sha,
                        "count": int(row.cnt or 0),
                        "documents": docs_by_sha.get(sha, [])[: int(max_docs_per_group or 20)],
                    }
                )

            return {"total": total_groups, "items": items}
        except Exception as exc:
            # Fall back to the Python scan path below (best-effort).
            logger.debug("Postgres duplicate-document query failed; falling back to Python scan: %s", exc)

    rows = base_query.with_entities(
        DBDocument.id,
        DBDocument.filename,
        DBDocument.status,
        DBDocument.dataset_id,
        DBDocument.created_at,
        DBDocument.doc_metadata,
    ).all()

    by_sha: dict[str, list[dict[str, Any]]] = {}
    for doc_id, filename, status, ds_id, created_at, meta in rows:
        metadata = meta if isinstance(meta, dict) else {}
        sha = str(metadata.get("file_sha256") or "").strip().lower()
        if not sha:
            continue
        by_sha.setdefault(sha, []).append(
            {
                "id": doc_id,
                "filename": filename,
                "status": str(status or ""),
                "dataset_id": ds_id,
                "created_at": created_at,
            }
        )

    def _dt_ts(value: Any) -> float:
        try:
            return float(value.timestamp()) if value is not None else 0.0
        except Exception:
            return 0.0

    groups_all: list[tuple[str, list[dict[str, Any]], float]] = []
    for sha, docs in by_sha.items():
        if len(docs) < int(min_count or 2):
            continue
        newest_ts = 0.0
        for doc in docs:
            newest_ts = max(newest_ts, _dt_ts(doc.get("created_at")))
        groups_all.append((sha, docs, newest_ts))

    total_groups = len(groups_all)
    groups_all.sort(key=lambda item: (-len(item[1]), -float(item[2] or 0.0), item[0]))

    items: list[dict[str, Any]] = []
    for sha, docs, _newest_ts in groups_all[: int(max_groups or 50)]:
        docs_sorted = sorted(docs, key=lambda doc: _dt_ts(doc.get("created_at")), reverse=True)
        items.append(
            {
                "file_sha256": sha,
                "count": len(docs),
                "documents": docs_sorted[: int(max_docs_per_group or 20)],
            }
        )

    return {"total": total_groups, "items": items}
