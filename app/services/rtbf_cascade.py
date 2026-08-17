"""
RTBF cascade scaffold (service-only).

This module provides a bounded, auditable orchestration layer for account-scoped
"right to be forgotten" cleanup across existing document lifecycle artifacts.

Current scope:
- identify candidate documents owned by / attributed to a subject account
- optionally execute the existing delete-document lifecycle
- invalidate dataset-scoped retrieval caches after successful deletes
- emit a compact audit event

Notes:
- This is intentionally a service-layer scaffold first; API/workflow surfaces can
  reuse this contract later.
- We rely on the existing document delete lifecycle for chunk/vector/KG/object
  cleanup to avoid duplicating side effects in a second code path.
"""


import contextlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.document import Document as DBDocument
from app.services.audit_log_service import audit_log_event
from app.services.corpus_cache_tokens import invalidate_dataset_cache_namespace
from app.services.retention_jobs import _resolve_delete_document_lifecycle

RTBF_CASCADE_SCHEMA_V1 = "mimirq.rtbf_cascade.v1"
RTBF_ARTIFACT_SCOPES = ["documents", "chunks", "kg", "vectors", "object_assets", "cache"]


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _safe_int(value: object, *, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _match_reason_list(doc: object, *, subject_account_id: str, subject_user_uuid: UUID | None) -> list[str]:
    reasons: list[str] = []
    if str(getattr(doc, "owner_id", "") or "").strip() == subject_account_id:
        reasons.append("owner_id")
    if str(getattr(doc, "lifecycle_owner", "") or "").strip() == subject_account_id:
        reasons.append("lifecycle_owner")
    if subject_user_uuid is not None and getattr(doc, "user_id", None) == subject_user_uuid:
        reasons.append("user_id")
    return reasons


def _list_rtbf_documents(
    db: Session,
    *,
    tenant_id: UUID,
    subject_account_id: str,
    max_docs: int = 100,
) -> list[dict[str, object]]:
    subject = str(subject_account_id or "").strip()
    if not subject:
        return []

    limit = max(1, int(max_docs or 0))
    try:
        subject_uuid = UUID(subject)
    except Exception:
        subject_uuid = None

    query = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id)
    predicates = [DBDocument.owner_id == subject, DBDocument.lifecycle_owner == subject]
    if subject_uuid is not None:
        predicates.append(DBDocument.user_id == subject_uuid)
    query = query.filter(or_(*predicates)).order_by(DBDocument.updated_at.asc(), DBDocument.id.asc())

    out: list[dict[str, object]] = []
    for doc in query.limit(limit).all():
        reasons = _match_reason_list(doc, subject_account_id=subject, subject_user_uuid=subject_uuid)
        if not reasons:
            continue
        out.append(
            {
                "document_id": getattr(doc, "id", None),
                "dataset_id": getattr(doc, "dataset_id", None),
                "owner_id": str(getattr(doc, "owner_id", "") or "").strip() or None,
                "filename": str(getattr(doc, "filename", "") or "").strip() or None,
                "match_reasons": reasons,
            }
        )
    return out


async def _run_delete_document_lifecycle(
    delete_document_lifecycle,
    *,
    document_id: UUID,
    tenant_id: UUID,
    actor_id: str,
    db: Session,
    max_retries: int,
) -> int:
    attempts = 0
    retries = max(0, int(max_retries or 0))
    while attempts <= retries:
        attempts += 1
        try:
            await delete_document_lifecycle(
                document_id=document_id,
                tenant_id=tenant_id,
                account_id=actor_id,
                db=db,
                enforce_permissions=False,
                enforce_membership=False,
            )
            return attempts
        except Exception:
            if attempts > retries:
                raise
    return attempts


def _invalidate_dataset_caches(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_ids: set[UUID],
    max_retries: int,
) -> int:
    invalidated = 0
    retries = max(0, int(max_retries or 0))
    for dataset_id in sorted(dataset_ids):
        attempts = 0
        while attempts <= retries:
            attempts += 1
            try:
                invalidate_dataset_cache_namespace(db, tenant_id=tenant_id, dataset_id=dataset_id)
                invalidated += 1
                break
            except Exception:
                if attempts > retries:
                    raise
    return invalidated


def _rtbf_summary_documents(candidates: list[dict[str, object]], *, dry_run: bool) -> list[dict[str, object]]:
    return [
        {
            "document_id": str(item.get("document_id") or ""),
            "dataset_id": (str(item.get("dataset_id")) if item.get("dataset_id") is not None else None),
            "filename": item.get("filename"),
            "match_reasons": list(item.get("match_reasons") or []),
            "status": "planned" if bool(dry_run) else "pending",
            "attempts": 0,
        }
        for item in candidates[:50]
    ]


def _increment_summary(summary: dict[str, object], key: str) -> None:
    summary[key] = int(summary.get(key, 0) or 0) + 1


def _update_summary_document(
    doc_state_by_id: dict[str, dict[str, object]],
    *,
    document_id: UUID,
    status: str,
    attempts: int,
    error: str | None = None,
) -> None:
    state = doc_state_by_id.get(str(document_id))
    if not isinstance(state, dict):
        return
    state["status"] = status
    state["attempts"] = int(attempts)
    if error is not None:
        state["error"] = error


def _build_rtbf_summary(
    *,
    tenant_id: UUID,
    subject: str,
    dry_run: bool,
    max_docs: int,
    max_retries: int,
    candidates: list[dict[str, object]],
    now0: datetime,
) -> dict[str, object]:
    return {
        "schema": RTBF_CASCADE_SCHEMA_V1,
        "tenant_id": str(tenant_id),
        "subject_account_id": subject,
        "dry_run": bool(dry_run),
        "max_docs": int(max_docs),
        "max_retries": int(max(0, int(max_retries or 0))),
        "artifact_scopes": list(RTBF_ARTIFACT_SCOPES),
        "eligible": int(len(candidates)),
        "deleted": 0,
        "errors": 0,
        "cache_invalidations": 0,
        "retried_documents": 0,
        "documents": _rtbf_summary_documents(candidates, dry_run=dry_run),
        "ran_at": now0.isoformat(),
    }


async def _execute_rtbf_cascade(
    *,
    summary: dict[str, object],
    candidates: list[dict[str, object]],
    tenant_id: UUID,
    actor_id: str,
    db: Session,
    max_retries: int,
) -> None:
    delete_document_lifecycle = _resolve_delete_document_lifecycle()
    successful_dataset_ids: set[UUID] = set()
    doc_state_by_id = {str(item.get("document_id") or ""): item for item in summary["documents"]}  # type: ignore[index]

    for item in candidates:
        document_id = item.get("document_id")
        if not isinstance(document_id, UUID):
            _increment_summary(summary, "errors")
            continue
        try:
            attempts = await _run_delete_document_lifecycle(
                delete_document_lifecycle,
                document_id=document_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
                db=db,
                max_retries=max_retries,
            )
            _update_summary_document(doc_state_by_id, document_id=document_id, status="deleted", attempts=attempts)
            if attempts > 1:
                _increment_summary(summary, "retried_documents")
            _increment_summary(summary, "deleted")
            dataset_id = item.get("dataset_id")
            if isinstance(dataset_id, UUID):
                successful_dataset_ids.add(dataset_id)
        except Exception as exc:  # noqa: BLE001
            _update_summary_document(
                doc_state_by_id,
                document_id=document_id,
                status="error",
                error=str(exc)[:200],
                attempts=int(max(1, int(max_retries or 0) + 1)),
            )
            _increment_summary(summary, "errors")

    if successful_dataset_ids:
        try:
            summary["cache_invalidations"] = int(
                _invalidate_dataset_caches(
                    db,
                    tenant_id=tenant_id,
                    dataset_ids=successful_dataset_ids,
                    max_retries=max_retries,
                )
            )
        except Exception:
            _increment_summary(summary, "errors")


def _audit_rtbf_summary(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: str,
    subject: str,
    dry_run: bool,
    summary: dict[str, object],
) -> None:
    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="privacy.rtbf.cascade",
        resource_type="subject",
        resource_id=subject,
        details={
            "dry_run": bool(dry_run),
            "eligible": int(summary.get("eligible", 0) or 0),
            "deleted": int(summary.get("deleted", 0) or 0),
            "errors": int(summary.get("errors", 0) or 0),
            "cache_invalidations": int(summary.get("cache_invalidations", 0) or 0),
            "artifact_scopes": list(RTBF_ARTIFACT_SCOPES),
        },
    )


async def run_rtbf_cascade(
    db: Session,
    *,
    tenant_id: UUID,
    subject_account_id: str,
    dry_run: bool,
    actor_id: str = "system:rtbf",
    max_docs: int = 100,
    max_retries: int = 1,
    now: datetime | None = None,
) -> dict[str, object]:
    now0 = now or _now_utc()
    subject = str(subject_account_id or "").strip()
    candidates = _list_rtbf_documents(
        db,
        tenant_id=tenant_id,
        subject_account_id=subject,
        max_docs=max_docs,
    )

    summary = _build_rtbf_summary(
        tenant_id=tenant_id,
        subject=subject,
        dry_run=dry_run,
        max_docs=max_docs,
        max_retries=max_retries,
        candidates=candidates,
        now0=now0,
    )

    if not dry_run and candidates:
        await _execute_rtbf_cascade(
            summary=summary,
            candidates=candidates,
            tenant_id=tenant_id,
            actor_id=str(actor_id),
            db=db,
            max_retries=max_retries,
        )

    with contextlib.suppress(Exception):
        _audit_rtbf_summary(
            db,
            tenant_id=tenant_id,
            actor_id=str(actor_id),
            subject=subject,
            dry_run=dry_run,
            summary=summary,
        )
    with contextlib.suppress(Exception):
        db.commit()

    return summary


__all__ = ["RTBF_ARTIFACT_SCOPES", "RTBF_CASCADE_SCHEMA_V1", "run_rtbf_cascade"]
