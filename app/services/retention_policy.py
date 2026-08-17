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


def upsert_retention_policy_metadata(
    meta: dict[str, Any], *, policy: DatasetRetentionPolicy | None, replace: bool
) -> bool:
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


def _build_version_row(
    *,
    document_id: UUID,
    active_key: str | None,
    pipeline_hash: str,
    doc_pipeline_key: str | None,
    chunk_count: int,
    first_chunk_at: datetime | None,
    last_chunk_at: datetime | None,
) -> _VersionRow | None:
    pipeline_hash_norm = str(pipeline_hash or "").strip()
    if not pipeline_hash_norm:
        return None
    key = str(doc_pipeline_key or "").strip() or f"{document_id}:{pipeline_hash_norm}"
    return _VersionRow(
        pipeline_hash=pipeline_hash_norm,
        doc_pipeline_key=key,
        chunk_count=int(chunk_count or 0),
        first_chunk_at=first_chunk_at,
        last_chunk_at=last_chunk_at,
        active=bool(active_key and key == active_key),
    )


def _sort_versions(versions: list[_VersionRow]) -> list[_VersionRow]:
    def _sort_key(version: _VersionRow) -> tuple[str, str]:
        ts = version.last_chunk_at or version.first_chunk_at
        return (ts.isoformat() if isinstance(ts, datetime) else "", version.pipeline_hash)

    return sorted(versions, key=_sort_key, reverse=True)


def _list_document_versions_from_grouped_rows(
    *,
    rows: list[tuple[Any, Any, Any, Any, Any]],
    document_id: UUID,
    active_key: str | None,
) -> list[_VersionRow]:
    versions: list[_VersionRow] = []
    for pipeline_hash, doc_pipeline_key, cnt, first_at, last_at in rows:
        version = _build_version_row(
            document_id=document_id,
            active_key=active_key,
            pipeline_hash=str(pipeline_hash or ""),
            doc_pipeline_key=str(doc_pipeline_key or ""),
            chunk_count=int(cnt or 0),
            first_chunk_at=first_at,
            last_chunk_at=last_at,
        )
        if version is not None:
            versions.append(version)
    return versions


def _list_document_versions_from_chunk_rows(
    *,
    rows: list[tuple[Any, Any]],
    document_id: UUID,
    active_key: str | None,
) -> list[_VersionRow]:
    by_key: dict[str, dict[str, Any]] = {}
    for meta, created_at in rows:
        metadata = meta if isinstance(meta, dict) else {}
        pipeline_hash = str(metadata.get("pipeline_hash") or "").strip()
        if not pipeline_hash:
            continue
        key = str(metadata.get("doc_pipeline_key") or "").strip() or f"{document_id}:{pipeline_hash}"
        state = by_key.setdefault(
            key,
            {"pipeline_hash": pipeline_hash, "chunk_count": 0, "first": None, "last": None},
        )
        state["chunk_count"] = int(state.get("chunk_count") or 0) + 1
        if not isinstance(created_at, datetime):
            continue
        if state["first"] is None or created_at < state["first"]:
            state["first"] = created_at
        if state["last"] is None or created_at > state["last"]:
            state["last"] = created_at

    versions: list[_VersionRow] = []
    for key, state in by_key.items():
        version = _build_version_row(
            document_id=document_id,
            active_key=active_key,
            pipeline_hash=str(state.get("pipeline_hash") or ""),
            doc_pipeline_key=key,
            chunk_count=int(state.get("chunk_count") or 0),
            first_chunk_at=state.get("first"),
            last_chunk_at=state.get("last"),
        )
        if version is not None:
            versions.append(version)
    return versions


def _list_document_versions_no_acl(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    active_hash: str | None,
) -> list[_VersionRow]:
    active_key = f"{document_id}:{active_hash}" if active_hash else None
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
        versions = _list_document_versions_from_grouped_rows(
            rows=list(rows),
            document_id=document_id,
            active_key=active_key,
        )
    except Exception:
        rows = (
            db.query(DocumentChunk.doc_metadata, DocumentChunk.created_at)
            .filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == document_id)
            .all()
        )
        versions = _list_document_versions_from_chunk_rows(
            rows=list(rows),
            document_id=document_id,
            active_key=active_key,
        )
    return _sort_versions(versions)


def _invalid_pipeline_hash_reason(pipeline_hash: str) -> str | None:
    pipeline_hash_norm = str(pipeline_hash or "").strip()
    if not pipeline_hash_norm:
        return "missing_pipeline_hash"
    if len(pipeline_hash_norm) > 64:
        return "pipeline_hash_too_long"
    return None


def _resolve_version_chunk_ids(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    target_key: str,
) -> list[UUID]:
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
        return [cid for (cid,) in rows if isinstance(cid, UUID)]
    except Exception:
        rows = (
            db.query(DocumentChunk.id, DocumentChunk.doc_metadata)
            .filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == document_id)
            .all()
        )
        return [
            cid
            for cid, metadata in rows
            if str((metadata if isinstance(metadata, dict) else {}).get("doc_pipeline_key") or "").strip() == target_key
        ]


def _delete_version_search_indexes(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    target_key: str,
) -> None:
    with contextlib.suppress(Exception):
        from app.services.indexer import Indexer

        Indexer(db).delete_document_chunk_vectors(
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


def _update_document_metadata_after_version_delete(
    *,
    doc: DBDocument,
    document_id: UUID,
    pipeline_hash: str,
    current_hash: str,
    active_hash: str,
) -> None:
    doc_meta = dict(getattr(doc, "doc_metadata", None) or {})
    if current_hash and current_hash == pipeline_hash:
        if active_hash:
            doc_meta["pipeline_hash"] = active_hash
        else:
            doc_meta.pop("pipeline_hash", None)
    provenance = doc_meta.get("pipeline_provenance_versions")
    if isinstance(provenance, dict) and pipeline_hash in provenance:
        updated = dict(provenance)
        updated.pop(pipeline_hash, None)
        doc_meta["pipeline_provenance_versions"] = updated
    if doc_meta != dict(getattr(doc, "doc_metadata", None) or {}):
        doc.doc_metadata = doc_meta


def _delete_version_chunk_rows(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    chunk_ids: list[UUID],
) -> None:
    db.query(DocumentChunk).filter(
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.document_id == document_id,
        DocumentChunk.id.in_(chunk_ids),
    ).delete(synchronize_session=False)


def _commit_best_effort(db: Session) -> None:
    db.commit()


def _cleanup_deleted_version_kg_best_effort(
    db: Session,
    *,
    tenant_id: UUID,
    chunk_ids: list[UUID],
    commit: bool,
) -> None:
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
            _commit_best_effort(db)
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()


def _audit_deleted_version_best_effort(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: str,
    document_id: UUID,
    pipeline_hash: str,
    deleted_chunk_count: int,
    commit: bool,
) -> None:
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="document.version.retention_delete",
            resource_type="document",
            resource_id=str(document_id),
            details={"pipeline_hash": pipeline_hash, "deleted_chunk_count": deleted_chunk_count},
        )
        if commit:
            _commit_best_effort(db)
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()


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
    invalid_reason = _invalid_pipeline_hash_reason(pipeline_hash_norm)
    if invalid_reason is not None:
        return {"ok": False, "reason": invalid_reason}

    doc = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id, DBDocument.id == document_id).first()
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
    chunk_ids = _resolve_version_chunk_ids(
        db,
        tenant_id=tenant_id,
        document_id=document_id,
        target_key=target_key,
    )
    if not chunk_ids:
        return {"ok": False, "reason": "version_not_found"}

    _delete_version_search_indexes(
        db,
        tenant_id=tenant_id,
        document_id=document_id,
        target_key=target_key,
    )
    _delete_version_chunk_rows(
        db,
        tenant_id=tenant_id,
        document_id=document_id,
        chunk_ids=chunk_ids,
    )
    _update_document_metadata_after_version_delete(
        doc=doc,
        document_id=document_id,
        pipeline_hash=pipeline_hash_norm,
        current_hash=current_hash,
        active_hash=active_hash,
    )

    if commit:
        _commit_best_effort(db)
    _cleanup_deleted_version_kg_best_effort(
        db,
        tenant_id=tenant_id,
        chunk_ids=chunk_ids,
        commit=commit,
    )
    _audit_deleted_version_best_effort(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        document_id=document_id,
        pipeline_hash=pipeline_hash_norm,
        deleted_chunk_count=len(chunk_ids),
        commit=commit,
    )

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


def _resolve_retention_action(policy: DatasetRetentionPolicy) -> str:
    action = str(policy.action or "archive").strip().lower()
    return action if action in {"archive", "delete"} else "archive"


def _retention_cutoffs(
    *,
    policy: DatasetRetentionPolicy,
    now: datetime,
) -> tuple[datetime | None, datetime | None]:
    cutoff_created_at = now - timedelta(days=int(policy.max_age_days)) if policy.max_age_days is not None else None
    cutoff_updated_at = (
        now - timedelta(days=int(policy.max_inactive_days)) if policy.max_inactive_days is not None else None
    )
    return cutoff_created_at, cutoff_updated_at


def _retention_summary(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    policy: DatasetRetentionPolicy,
    dry_run: bool,
    action: str,
    cutoff_created_at: datetime | None,
    cutoff_updated_at: datetime | None,
    now: datetime,
) -> dict[str, Any]:
    return {
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
        "ran_at": now.isoformat(),
    }


def _archive_expired_documents(
    db: Session,
    *,
    expired_docs: list[Any],
    now: datetime,
    summary: dict[str, Any],
    tenant_id: UUID,
    dataset_id: UUID,
) -> None:
    archived_count = 0
    for doc in expired_docs:
        if getattr(doc, "archived_at", None) is None:
            doc.archived_at = now
            archived_count += 1
    try:
        db.commit()
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()
        summary["documents"]["errors"] += int(archived_count)
        return
    summary["documents"]["archived"] += int(archived_count)
    with contextlib.suppress(Exception):
        summary["cache_invalidation"] = invalidate_dataset_cache_namespace(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
        )


async def _delete_expired_documents(
    db: Session,
    *,
    expired_docs: list[Any],
    tenant_id: UUID,
    dataset_id: UUID,
    actor_id: str,
    summary: dict[str, Any],
) -> None:
    from app.services.retention_jobs import _resolve_delete_document_lifecycle  # noqa: WPS433

    delete_lifecycle = _resolve_delete_document_lifecycle()
    for doc in expired_docs:
        document_id = getattr(doc, "id", None)
        if document_id is None:
            summary["documents"]["not_found"] += 1
            continue
        try:
            await delete_lifecycle(
                document_id=document_id,
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
    with contextlib.suppress(Exception):
        summary["cache_invalidation"] = invalidate_dataset_cache_namespace(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
        )
    with contextlib.suppress(Exception):
        db.commit()


async def _run_document_retention_action(
    db: Session,
    *,
    expired_docs: list[Any],
    dry_run: bool,
    action: str,
    summary: dict[str, Any],
    tenant_id: UUID,
    dataset_id: UUID,
    actor_id: str,
    now: datetime,
) -> None:
    if dry_run or not expired_docs:
        return
    if action == "archive":
        _archive_expired_documents(
            db,
            expired_docs=expired_docs,
            now=now,
            summary=summary,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
        )
        return
    await _delete_expired_documents(
        db,
        expired_docs=expired_docs,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        actor_id=actor_id,
        summary=summary,
    )


def _candidate_documents_for_version_pruning(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    max_versions: int,
    max_docs: int,
) -> list[UUID]:
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
        return [doc_id for doc_id, _cnt in rows if isinstance(doc_id, UUID)]
    except Exception:
        return []


def _retained_pipeline_hashes(versions: list[_VersionRow], *, max_versions: int) -> set[str]:
    keep: set[str] = set()
    for version in versions:
        if version.active:
            keep.add(version.pipeline_hash)
            break
    for version in versions:
        if len(keep) >= max_versions:
            break
        keep.add(version.pipeline_hash)
    return keep


def _prune_document_versions(
    db: Session,
    *,
    tenant_id: UUID,
    doc_id: UUID,
    policy: DatasetRetentionPolicy,
    dry_run: bool,
    actor_id: str,
    max_versions_pruned: int,
    pruned: int,
    summary: dict[str, Any],
) -> int:
    doc = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id, DBDocument.id == doc_id).first()
    if doc is None:
        return pruned
    active_hash = get_active_pipeline_hash(dict(getattr(doc, "doc_metadata", None) or {}))
    versions = _list_document_versions_no_acl(db, tenant_id=tenant_id, document_id=doc_id, active_hash=active_hash)
    max_versions = int(policy.max_versions or 0)
    if len(versions) <= max_versions:
        return pruned
    keep = _retained_pipeline_hashes(versions, max_versions=max_versions)
    for version in reversed(versions):
        if version.pipeline_hash in keep:
            continue
        if max_versions_pruned > 0 and pruned >= max_versions_pruned:
            break
        if dry_run:
            pruned += 1
            summary["versions"]["versions_pruned"] += 1
            continue
        result = delete_document_version_best_effort(
            db,
            tenant_id=tenant_id,
            document_id=doc_id,
            pipeline_hash=version.pipeline_hash,
            actor_id=str(actor_id),
            commit=True,
        )
        if bool(result.get("ok")):
            pruned += 1
            summary["versions"]["versions_pruned"] += 1
        else:
            summary["versions"]["errors"] += 1
    return pruned


def _audit_retention_sweep_best_effort(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: str,
    dataset_id: UUID,
    dry_run: bool,
    action: str,
    max_docs: int,
    summary: dict[str, Any],
) -> None:
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

    ds = db.query(Dataset).filter(Dataset.tenant_id == tenant_id, Dataset.id == dataset_id).first()
    if ds is None:
        return {"ok": False, "reason": "dataset_not_found", "dataset_id": str(dataset_id)}

    action = _resolve_retention_action(policy)
    cutoff_created_at, cutoff_updated_at = _retention_cutoffs(policy=policy, now=now0)
    summary = _retention_summary(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        policy=policy,
        dry_run=dry_run,
        action=action,
        cutoff_created_at=cutoff_created_at,
        cutoff_updated_at=cutoff_updated_at,
        now=now0,
    )

    expired_q = _expired_documents_query(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        cutoff_created_at=cutoff_created_at,
        cutoff_updated_at=cutoff_updated_at,
    ).limit(max_docs)

    expired_docs = list(expired_q.all() or [])
    summary["documents"]["eligible"] = int(len(expired_docs))
    await _run_document_retention_action(
        db,
        expired_docs=expired_docs,
        dry_run=dry_run,
        action=action,
        summary=summary,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        actor_id=actor_id,
        now=now0,
    )

    # ---- Version pruning (max_versions) ----
    if policy.max_versions is not None and int(policy.max_versions) > 0 and max_versions_pruned_i != 0:
        candidates = _candidate_documents_for_version_pruning(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            max_versions=int(policy.max_versions),
            max_docs=max_docs,
        )
        pruned = 0
        for doc_id in candidates:
            if max_versions_pruned_i > 0 and pruned >= max_versions_pruned_i:
                break
            summary["versions"]["documents_scanned"] += 1
            pruned = _prune_document_versions(
                db,
                tenant_id=tenant_id,
                doc_id=doc_id,
                policy=policy,
                dry_run=dry_run,
                actor_id=actor_id,
                max_versions_pruned=max_versions_pruned_i,
                pruned=pruned,
                summary=summary,
            )

    _audit_retention_sweep_best_effort(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        dataset_id=dataset_id,
        dry_run=dry_run,
        action=action,
        max_docs=max_docs,
        summary=summary,
    )

    return summary


__all__ = [
    "DatasetRetentionPolicy",
    "delete_document_version_best_effort",
    "parse_retention_policy_from_metadata",
    "run_dataset_retention_sweep",
    "upsert_retention_policy_metadata",
]
