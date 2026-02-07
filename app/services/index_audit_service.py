from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.services.dataset_service import DatasetService


def compute_index_audit_summary(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    active_documents: int,
    active_chunks: int,
    vector_id_missing: int,
    vector_ids_checked: list[str],
    vector_ids_existing: set[str] | None,
    milvus_ids_sample: list[str] | None = None,
    active_chunk_ids_present: set[str] | None = None,
    sample_limit: int = 20,
) -> dict[str, Any]:
    """
    Pure helper: turn raw counts + id sets into a JSON-safe audit payload.

    This is intended for unit tests and for keeping the API handler thin.
    """
    cap = max(0, int(sample_limit or 0))

    checked = [str(x) for x in (vector_ids_checked or []) if str(x).strip()]
    existing = set(str(x) for x in (vector_ids_existing or set()) if str(x).strip())

    missing_in_vector = [vid for vid in checked if vid not in existing] if checked else []
    missing_in_vector_sorted = sorted(set(missing_in_vector))

    orphan_sample: list[str] = []
    if milvus_ids_sample and active_chunk_ids_present is not None:
        orphan_sample = [str(x) for x in milvus_ids_sample if str(x) not in active_chunk_ids_present]
        orphan_sample = sorted(set(orphan_sample))

    def _sample(values: list[str]) -> list[str]:
        if cap <= 0:
            return []
        return values[:cap]

    return {
        "tenant_id": str(tenant_id),
        "dataset_id": str(dataset_id),
        "vector_backend": str(getattr(settings, "VECTOR_BACKEND", "") or ""),
        "active_documents": int(active_documents),
        "active_chunks": int(active_chunks),
        "vector_id_missing": int(vector_id_missing),
        "vector_ids_checked": len(checked),
        "vector_ids_missing_in_backend": len(missing_in_vector_sorted),
        "vector_ids_missing_in_backend_sample": _sample(missing_in_vector_sorted),
        "milvus_ids_sampled": int(len(milvus_ids_sample or [])),
        "milvus_orphan_ids_sample": _sample(orphan_sample),
    }


def run_dataset_index_audit(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    max_check_ids: int = 5000,
    milvus_list_limit: int = 2000,
    sample_limit: int = 20,
) -> dict[str, Any]:
    """
    Dataset-scoped index audit (admin-only entry point).

    This is best-effort by design:
    - It should never hard-fail the request due to vector backend errors.
    - It is bounded (max_check_ids / milvus_list_limit) to avoid massive scans.
    """
    # Ensure the caller is at least a tenant member; the API layer enforces admin role separately.
    DatasetService.ensure_member(db, tenant_id, account_id)
    DatasetService.get_dataset(db, tenant_id, dataset_id)

    # "Active" documents: searchable in RAG (mirrors retrieval readiness checks).
    doc_ready_clause = or_(
        DBDocument.status == "completed",
        (DBDocument.doc_metadata["active_pipeline_ready"].astext == "true"),  # type: ignore[attr-defined]
    )
    docs_q = (
        db.query(DBDocument.id, DBDocument.doc_metadata)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.archived_at.is_(None),
            DBDocument.disabled_at.is_(None),
        )
        .filter(doc_ready_clause)
    )

    active_doc_ids = [row[0] for row in docs_q.all() if row and row[0]]
    active_documents = len(active_doc_ids)

    # Active pipeline hash: chunks must match this version to be considered "active".
    doc_active_hash = func.coalesce(
        DBDocument.doc_metadata["active_pipeline_hash"].astext,  # type: ignore[attr-defined]
        DBDocument.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
        "",
    )
    chunk_hash = func.coalesce(
        DocumentChunk.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
        "",
    )

    chunks_q = (
        db.query(DocumentChunk.id, DocumentChunk.vector_id)
        .join(
            DBDocument,
            and_(
                DBDocument.id == DocumentChunk.document_id,
                DBDocument.tenant_id == DocumentChunk.tenant_id,
            ),
        )
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.archived_at.is_(None),
            DBDocument.disabled_at.is_(None),
        )
        .filter(doc_ready_clause)
        .filter(DocumentChunk.disabled_at.is_(None))
        .filter(chunk_hash == doc_active_hash)
    )

    active_chunks = int(
        chunks_q.with_entities(func.count(DocumentChunk.id)).scalar()  # type: ignore[arg-type]
        or 0
    )

    vector_id_missing = int(
        chunks_q.filter(or_(DocumentChunk.vector_id.is_(None), DocumentChunk.vector_id == ""))
        .with_entities(func.count(DocumentChunk.id))
        .scalar()  # type: ignore[arg-type]
        or 0
    )

    cap_check = max(0, int(max_check_ids or 0))
    if cap_check <= 0:
        cap_check = 5000

    vec_rows = (
        chunks_q.filter(DocumentChunk.vector_id.isnot(None))
        .with_entities(DocumentChunk.vector_id)
        .order_by(DocumentChunk.updated_at.desc().nullslast())  # type: ignore[attr-defined]
        .limit(cap_check)
        .all()
    )
    vector_ids_checked = [str(row[0]) for row in vec_rows if row and row[0]]

    vector_ids_existing: set[str] | None = None
    milvus_ids_sample: list[str] | None = None
    active_chunk_ids_present: set[str] | None = None

    vector_backend = str(getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus").strip().lower()
    if vector_backend == "milvus" and vector_ids_checked:
        try:
            from app.storage.vector.milvus import milvus_store

            vector_ids_existing = milvus_store.fetch_existing_ids(vector_ids_checked)
        except Exception:
            vector_ids_existing = None

    # Orphan sample: list a bounded set of Milvus ids for the dataset and check if DB contains them.
    if vector_backend == "milvus" and int(milvus_list_limit or 0) > 0:
        try:
            from app.storage.vector.milvus import milvus_store

            milvus_ids_sample = milvus_store.list_ids_by_dataset(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                limit=max(0, int(milvus_list_limit or 0)),
                offset=0,
            )
        except Exception:
            milvus_ids_sample = None

    if milvus_ids_sample:
        # Only UUID-like ids can map back to DocumentChunk.id.
        want: list[UUID] = []
        for raw in milvus_ids_sample:
            try:
                want.append(UUID(str(raw)))
            except Exception:
                continue

        if want:
            rows = chunks_q.filter(DocumentChunk.id.in_(want)).with_entities(DocumentChunk.id).all()
            active_chunk_ids_present = {str(r[0]) for r in rows if r and r[0]}
        else:
            active_chunk_ids_present = set()

    return compute_index_audit_summary(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        active_documents=active_documents,
        active_chunks=active_chunks,
        vector_id_missing=vector_id_missing,
        vector_ids_checked=vector_ids_checked,
        vector_ids_existing=vector_ids_existing,
        milvus_ids_sample=milvus_ids_sample,
        active_chunk_ids_present=active_chunk_ids_present,
        sample_limit=sample_limit,
    )


__all__ = [
    "compute_index_audit_summary",
    "run_dataset_index_audit",
]

