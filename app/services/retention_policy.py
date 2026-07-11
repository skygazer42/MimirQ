"""
Dataset-level retention policy automation (Gap9).

This module provides:
- Metadata helpers to store/parse DatasetRetentionPolicy in datasets.metadata
- A bounded retention "sweep" runner intended for cron automation

Design goals:
- Best-effort + bounded: avoid accidental mass deletes
- Auditable: record a small PII-safe audit summary per sweep
- Reuse existing delete/version cleanup logic where possible
"""


import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.api.schemas.dataset import DatasetRetentionPolicy
from app.core.pipeline_versions import get_active_pipeline_hash
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.core.logging import get_logger
from app.services.audit_log_service import audit_log_event
from app.services.corpus_cache_tokens import invalidate_dataset_cache_namespace

logger = get_logger("retention_policy")


def parse_retention_policy_from_metadata(metadata: dict[str, Any]) -> DatasetRetentionPolicy | None:
    """Parse DatasetRetentionPolicy from datasets.metadata (best-effort)."""
    if not isinstance(metadata, dict):
        return None
    raw = metadata.get("retention_policy")
    if not isinstance(raw, dict):
        return None
    try:
        policy = DatasetRetentionPolicy(**raw)
    except ValidationError:
        return None
    return policy


def upsert_retention_policy_metadata(meta: dict[str, Any], *, policy: DatasetRetentionPolicy | None, replace: bool) -> bool:
    """
    Upsert retention_policy into dataset metadata.

    Semantics:
    - policy is None:
      - replace=true -> remove key
      - replace=false -> no-op
    - policy provided:
      - store model_dump(exclude_none=True)
    """
    if not isinstance(meta, dict):
        return False

    if policy is None:
        if replace and "retention_policy" in meta:
            meta.pop("retention_policy", None)
            return True
        return False

    payload = policy.model_dump(exclude_none=True)
    if not payload:
        if replace and "retention_policy" in meta:
            meta.pop("retention_policy", None)
            return True
        return False

    before = meta.get("retention_policy")
    if before != payload:
        meta["retention_policy"] = payload
        return True
    return False


@dataclass(frozen=True)
class _VersionRow:
    pipeline_hash: str
    doc_pipeline_key: str
    chunk_count: int
    first_chunk_at: datetime | None
    last_chunk_at: datetime | None
    active: bool


def _list_document_versions_no_acl(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    active_hash: str | None,
) -> list[_VersionRow]:
    active_key = f"{document_id}:{active_hash}" if active_hash else None
    versions: list[_VersionRow] = []
    try:
        rows = (
            db.query(
                DocumentChunk.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
                DocumentChunk.doc_metadata["doc_pipeline_key"].astext,  # type: ignore[attr-defined]
                func.count(DocumentChunk.id),
                func.min(DocumentChunk.created_at),
                func.max(DocumentChunk.created_at),
            )
            .filter(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id == document_id,
            )
            .group_by(
                DocumentChunk.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
                DocumentChunk.doc_metadata["doc_pipeline_key"].astext,  # type: ignore[attr-defined]
            )
            .all()
        )
        for pipeline_hash, doc_pipeline_key, cnt, first_at, last_at in rows:
            ph = str(pipeline_hash or "").strip()
            if not ph:
                continue
            key = str(doc_pipeline_key or "").strip() or f"{document_id}:{ph}"
            versions.append(
                _VersionRow(
                    pipeline_hash=ph,
                    doc_pipeline_key=key,
                    chunk_count=int(cnt or 0),
                    first_chunk_at=first_at,
                    last_chunk_at=last_at,
                    active=bool(active_key and key == active_key),
                )
            )
    except Exception:
        # Fallback: scan chunks in Python (bounded by document size; acceptable for retention sweeps).
        rows = (
            db.query(DocumentChunk.doc_metadata, DocumentChunk.created_at)
            .filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == document_id)
            .all()
        )
        by_key: dict[str, dict[str, Any]] = {}
        for meta, created_at in rows:
            m = meta if isinstance(meta, dict) else {}
            ph = str(m.get("pipeline_hash") or "").strip()
            if not ph:
                continue
            key = str(m.get("doc_pipeline_key") or "").strip() or f"{document_id}:{ph}"
            state = by_key.setdefault(
                key,
                {"pipeline_hash": ph, "chunk_count": 0, "first": None, "last": None},
            )
            state["chunk_count"] = int(state.get("chunk_count") or 0) + 1
            if isinstance(created_at, datetime):
                if state["first"] is None or created_at < state["first"]:
                    state["first"] = created_at
                if state["last"] is None or created_at > state["last"]:
                    state["last"] = created_at

        for key, state in by_key.items():
            ph = str(state.get("pipeline_hash") or "").strip()
            if not ph:
                continue
            versions.append(
                _VersionRow(
                    pipeline_hash=ph,
                    doc_pipeline_key=key,
                    chunk_count=int(state.get("chunk_count") or 0),
                    first_chunk_at=state.get("first"),
                    last_chunk_at=state.get("last"),
                    active=bool(active_key and key == active_key),
                )
            )

    # Sort newest first by last_chunk_at (fallback to first_chunk_at / pipeline_hash).
    def _sort_key(v: _VersionRow) -> tuple:
        ts = v.last_chunk_at or v.first_chunk_at
        ts_s = ts.isoformat() if isinstance(ts, datetime) else ""
        return (ts_s, v.pipeline_hash)

    versions.sort(key=_sort_key, reverse=True)
    return versions


def delete_document_version_best_effort(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    pipeline_hash: str,
    actor_id: str,
    commit: bool,
) -> dict[str, Any]:
    """
    Delete a non-active pipeline version without requiring an authenticated account.

    Mirrors the API endpoint semantics but skips permission checks.
    """
    pipeline_hash_norm = str(pipeline_hash or "").strip()
    if not pipeline_hash_norm:
        return {"ok": False, "reason": "missing_pipeline_hash"}
    if len(pipeline_hash_norm) > 64:
        return {"ok": False, "reason": "pipeline_hash_too_long"}

    doc = (
        db.query(DBDocument)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.id == document_id)
        .first()
    )
    if doc is None:
        return {"ok": False, "reason": "doc_not_found"}

    doc_status = str(getattr(doc, "status", "") or "").lower()
    doc_meta = dict(getattr(doc, "doc_metadata", None) or {})
    current_hash = str(doc_meta.get("pipeline_hash") or "").strip()
    active_hash = str(doc_meta.get("active_pipeline_hash") or doc_meta.get("pipeline_hash") or "").strip()
    if active_hash and pipeline_hash_norm == active_hash:
        return {"ok": False, "reason": "active_version"}
    if doc_status in {"pending", "processing"} and current_hash == pipeline_hash_norm:
        return {"ok": False, "reason": "in_progress_version"}

    target_key = f"{document_id}:{pipeline_hash_norm}"

    # Resolve chunk ids for this version.
    chunk_ids: list[UUID] = []
    try:
        rows = (
            db.query(DocumentChunk.id)
            .filter(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id == document_id,
                DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key,  # type: ignore[attr-defined]
            )
            .all()
        )
        chunk_ids = [cid for (cid,) in rows if isinstance(cid, UUID)]
    except Exception:
        rows = (
            db.query(DocumentChunk.id, DocumentChunk.doc_metadata)
            .filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == document_id)
            .all()
        )
        for cid, cmeta in rows:
            m = cmeta if isinstance(cmeta, dict) else {}
            key = str(m.get("doc_pipeline_key") or "").strip()
            if key == target_key:
                chunk_ids.append(cid)

    if not chunk_ids:
        return {"ok": False, "reason": "version_not_found"}

    # Best-effort: remove vectors + BM25 entries for the version.
    with contextlib.suppress(Exception):
        from app.storage.vector.factory import get_vector_store

        get_vector_store().delete_by_document_id_and_filter(
            document_id=document_id,
            tenant_id=tenant_id,
            metadata_filter={"doc_pipeline_key": {"$eq": target_key}},
        )
    with contextlib.suppress(Exception):
        from app.rag.retriever import hybrid_retriever

        hybrid_retriever.remove_from_bm25_index_by_metadata_filter(
            tenant_id=tenant_id,
            metadata_filter={"doc_pipeline_key": {"$eq": target_key}},
        )

    db.query(DocumentChunk).filter(
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.document_id == document_id,
        DocumentChunk.id.in_(chunk_ids),
    ).delete(synchronize_session=False)

    # If deleting the current pipeline (but not active), reset it to active.
    if current_hash and current_hash == pipeline_hash_norm:
        if active_hash:
            doc_meta["pipeline_hash"] = active_hash
        else:
            doc_meta.pop("pipeline_hash", None)
        doc.doc_metadata = doc_meta

    # Drop provenance snapshot entry (best-effort).
    prov = doc_meta.get("pipeline_provenance_versions")
    if isinstance(prov, dict) and pipeline_hash_norm in prov:
        prov2 = dict(prov)
        prov2.pop(pipeline_hash_norm, None)
        doc_meta["pipeline_provenance_versions"] = prov2
        doc.doc_metadata = doc_meta

    if commit:
        db.commit()

    # Best-effort: cleanup KG artifacts derived from the deleted version.
    try:
        from app.rag.kg.models import KgRelation
        from app.services.indexer import Indexer

        db.query(KgRelation).filter(KgRelation.tenant_id == tenant_id, KgRelation.chunk_id.in_(chunk_ids)).delete(
            synchronize_session=False
        )
        Indexer(db).delete_event_indexes_for_chunks(
            tenant_id=tenant_id,
            chunk_ids=chunk_ids,
            commit=False,
            prune_orphan_entities=True,
        )
        if commit:
            db.commit()
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()

    # Best-effort audit log (commit separately; never block sweep).
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="document.version.retention_delete",
            resource_type="document",
            resource_id=str(document_id),
            details={"pipeline_hash": pipeline_hash_norm, "deleted_chunk_count": len(chunk_ids)},
        )
        if commit:
            db.commit()
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()

    return {"ok": True, "deleted_chunk_count": int(len(chunk_ids))}


def _expired_documents_query(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    cutoff_created_at: datetime | None,
    cutoff_updated_at: datetime | None,
) -> Any:  # noqa: ANN401 - SQLAlchemy query
    q = (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.archived_at.is_(None),
            DBDocument.disabled_at.is_(None),
        )
        .order_by(DBDocument.updated_at.asc().nullslast(), DBDocument.id.asc())
    )

    clauses = []
    if cutoff_created_at is not None:
        clauses.append(DBDocument.created_at <= cutoff_created_at)
    if cutoff_updated_at is not None:
        clauses.append(DBDocument.updated_at <= cutoff_updated_at)
    if clauses:
        q = q.filter(or_(*clauses))
    else:
        # No expiry condition configured => no-op query.
        q = q.filter(DBDocument.id == None)  # noqa: E711
    return q


async def run_dataset_retention_sweep(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    policy: DatasetRetentionPolicy,
    dry_run: bool,
    max_documents: int,
    max_versions_pruned: int,
    actor_id: str = "system:retention",
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Run dataset retention sweep for one dataset.

    Output is intentionally PII-safe: counts only (no raw doc ids).
    """
    now0 = now or datetime.now(UTC)
    max_docs = max(1, int(max_documents or 0))
    max_versions_pruned_i = max(0, int(max_versions_pruned or 0))

    ds = (
        db.query(Dataset)
        .filter(Dataset.tenant_id == tenant_id, Dataset.id == dataset_id)
        .first()
    )
    if ds is None:
        return {"ok": False, "reason": "dataset_not_found", "dataset_id": str(dataset_id)}

    action = str(policy.action or "archive").strip().lower()
    if action not in {"archive", "delete"}:
        action = "archive"

    cutoff_created_at = None
    cutoff_updated_at = None
    if policy.max_age_days is not None:
        cutoff_created_at = now0 - timedelta(days=int(policy.max_age_days))
    if policy.max_inactive_days is not None:
        cutoff_updated_at = now0 - timedelta(days=int(policy.max_inactive_days))

    summary: dict[str, Any] = {
        "ok": True,
        "tenant_id": str(tenant_id),
        "dataset_id": str(dataset_id),
        "dry_run": bool(dry_run),
        "policy": policy.model_dump(exclude_none=True),
        "action": action,
        "cutoffs": {
            "created_at_lte": cutoff_created_at.isoformat() if cutoff_created_at else None,
            "updated_at_lte": cutoff_updated_at.isoformat() if cutoff_updated_at else None,
        },
        "documents": {
            "eligible": 0,
            "archived": 0,
            "deleted": 0,
            "not_found": 0,
            "conflicts": 0,
            "errors": 0,
        },
        "versions": {
            "max_versions": int(policy.max_versions) if policy.max_versions is not None else None,
            "documents_scanned": 0,
            "versions_pruned": 0,
            "errors": 0,
        },
        "cache_invalidation": None,
        "ran_at": now0.isoformat(),
    }

    expired_q = _expired_documents_query(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        cutoff_created_at=cutoff_created_at,
        cutoff_updated_at=cutoff_updated_at,
    ).limit(max_docs)

    expired_docs = list(expired_q.all() or [])
    summary["documents"]["eligible"] = int(len(expired_docs))

    if not dry_run and expired_docs:
        if action == "archive":
            archived_count = 0
            for doc in expired_docs:
                if getattr(doc, "archived_at", None) is None:
                    doc.archived_at = now0
                    archived_count += 1
            try:
                db.commit()
            except Exception:
                with contextlib.suppress(Exception):
                    db.rollback()
                summary["documents"]["errors"] += int(archived_count)
            else:
                summary["documents"]["archived"] += int(archived_count)
                # Touch dataset.updated_at to invalidate dataset-scoped retrieval caches only after commit.
                with contextlib.suppress(Exception):
                    summary["cache_invalidation"] = invalidate_dataset_cache_namespace(
                        db,
                        tenant_id=tenant_id,
                        dataset_id=dataset_id,
                    )
        else:
            # Delete uses the existing document delete lifecycle (cascades chunks/vectors/KG/object assets).
            from app.services.retention_jobs import _resolve_delete_document_lifecycle  # noqa: WPS433

            delete_lifecycle = _resolve_delete_document_lifecycle()
            for doc in expired_docs:
                did = getattr(doc, "id", None)
                if did is None:
                    summary["documents"]["not_found"] += 1
                    continue
                try:
                    await delete_lifecycle(
                        document_id=did,
                        tenant_id=tenant_id,
                        account_id=str(actor_id),
                        db=db,
                        enforce_permissions=False,
                        enforce_membership=False,
                    )
                    summary["documents"]["deleted"] += 1
                except Exception as exc:  # noqa: BLE001
                    status_code = getattr(exc, "status_code", None)
                    if status_code == 404:
                        summary["documents"]["not_found"] += 1
                    elif status_code in (409, 413, 429, 503):
                        summary["documents"]["conflicts"] += 1
                    else:
                        summary["documents"]["errors"] += 1

            # Best-effort invalidate dataset caches when documents were deleted.
            with contextlib.suppress(Exception):
                summary["cache_invalidation"] = invalidate_dataset_cache_namespace(
                    db,
                    tenant_id=tenant_id,
                    dataset_id=dataset_id,
                )
            with contextlib.suppress(Exception):
                db.commit()

    # ---- Version pruning (max_versions) ----
    if policy.max_versions is not None and int(policy.max_versions) > 0 and max_versions_pruned_i != 0:
        max_versions = int(policy.max_versions)

        # Select candidate documents with too many versions (best-effort SQL; bounded).
        candidates: list[UUID] = []
        try:
            rows = (
                db.query(
                    DocumentChunk.document_id,
                    func.count(func.distinct(DocumentChunk.doc_metadata["pipeline_hash"].astext)),  # type: ignore[attr-defined]
                )
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
                .group_by(DocumentChunk.document_id)
                .having(func.count(func.distinct(DocumentChunk.doc_metadata["pipeline_hash"].astext)) > max_versions)  # type: ignore[attr-defined]
                .order_by(func.count(func.distinct(DocumentChunk.doc_metadata["pipeline_hash"].astext)).desc())  # type: ignore[attr-defined]
                .limit(max_docs)
                .all()
            )
            candidates = [doc_id for doc_id, _cnt in rows if isinstance(doc_id, UUID)]
        except Exception:
            candidates = []

        pruned = 0
        for doc_id in candidates:
            if max_versions_pruned_i > 0 and pruned >= max_versions_pruned_i:
                break
            summary["versions"]["documents_scanned"] += 1

            doc = (
                db.query(DBDocument)
                .filter(DBDocument.tenant_id == tenant_id, DBDocument.id == doc_id)
                .first()
            )
            if doc is None:
                continue

            meta = dict(getattr(doc, "doc_metadata", None) or {})
            active_hash = get_active_pipeline_hash(meta)
            versions = _list_document_versions_no_acl(db, tenant_id=tenant_id, document_id=doc_id, active_hash=active_hash)
            if len(versions) <= max_versions:
                continue

            # Keep: active + (max_versions-1) most recent non-active versions.
            keep: set[str] = set()
            for v in versions:
                if v.active:
                    keep.add(v.pipeline_hash)
                    break
            for v in versions:
                if len(keep) >= max_versions:
                    break
                if v.pipeline_hash in keep:
                    continue
                keep.add(v.pipeline_hash)

            # Delete oldest first among deletable versions.
            deletable = [v for v in reversed(versions) if v.pipeline_hash not in keep]
            for v in deletable:
                if max_versions_pruned_i > 0 and pruned >= max_versions_pruned_i:
                    break
                if dry_run:
                    pruned += 1
                    summary["versions"]["versions_pruned"] += 1
                    continue

                res = delete_document_version_best_effort(
                    db,
                    tenant_id=tenant_id,
                    document_id=doc_id,
                    pipeline_hash=v.pipeline_hash,
                    actor_id=str(actor_id),
                    commit=True,
                )
                if bool(res.get("ok")):
                    pruned += 1
                    summary["versions"]["versions_pruned"] += 1
                else:
                    summary["versions"]["errors"] += 1

    # Best-effort run-level audit log (commit separately; never block sweep).
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=str(actor_id),
            action="dataset.retention.sweep",
            resource_type="dataset",
            resource_id=str(dataset_id),
            details={
                "dry_run": bool(dry_run),
                "action": action,
                "max_documents": int(max_docs),
                "documents": dict(summary.get("documents") or {}),
                "versions": dict(summary.get("versions") or {}),
                "policy": summary.get("policy"),
                "cutoffs": summary.get("cutoffs"),
            },
        )
        db.commit()
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()

    return summary


__all__ = [
    "DatasetRetentionPolicy",
    "delete_document_version_best_effort",
    "parse_retention_policy_from_metadata",
    "run_dataset_retention_sweep",
    "upsert_retention_policy_metadata",
]
