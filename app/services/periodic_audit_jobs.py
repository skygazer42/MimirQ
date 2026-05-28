"""
Periodic audit job helpers (ops automation).

Purpose:
- Run bounded, PII-safe "health" audits periodically (cron / Kubernetes CronJob).
- Write a small summary to audit logs (best-effort; fail-open).

Currently implemented:
- Daily dataset index-audit summary (vector backend consistency)
- Daily evidence reference drift audit summary (ground-truth pointer consistency)

Design principles (mirrors retention/stale jobs):
- Bounded: callers provide max_datasets + per-audit bounds
- Auditable: best-effort audit_log_event with small payloads
- Fail-open: never crash product flows due to automation
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.document import Document, DocumentPermission
from app.models.evidence import EvidenceItem, EvidenceSuite
from app.models.group_permissions import DatasetGroupPermission, DocumentGroupPermission
from app.models.tenant_group import TenantGroup, TenantGroupMember
from app.rag.core.logging import get_logger
from app.services.audit_log_service import audit_log_event
from app.services.embedding_drift_monitor import run_embedding_drift_monitor
from app.services.evidence_drift_audit_service import audit_reference_sources_drift
from app.services.index_audit_service import run_dataset_index_audit_internal

logger = get_logger(__name__)
SYSTEM_PERIODIC_AUDIT_ACTOR_ID = "system:periodic_audit"


def _dt_to_json(v: datetime | None) -> str | None:
    if v is None:
        return None
    try:
        s = v.astimezone(UTC).isoformat()
    except Exception:
        return None
    if s.endswith("+00:00"):
        s = s[:-6] + "Z"
    return s


def _bounded_top_counts(counter: Counter[str], *, max_items: int) -> dict[str, int]:
    out: dict[str, int] = {}
    for k, v in counter.most_common(max(0, int(max_items or 0))):
        out[str(k)] = int(v)
    return out


def _audit_already_written(
    db: Session,
    *,
    tenant_id: UUID,
    action: str,
    resource_type: str,
    report_date: str,
) -> bool:
    try:
        row = (
            db.query(AuditLog.id)
            .filter(
                AuditLog.tenant_id == tenant_id,
                AuditLog.action == str(action),
                AuditLog.resource_type == str(resource_type),
                AuditLog.resource_id == str(report_date),
            )
            .limit(1)
            .first()
        )
        return bool(row)
    except Exception:
        return False


def _list_dataset_ids_for_index_audit(
    db: Session,
    *,
    tenant_id: UUID,
    max_datasets: int,
) -> list[UUID]:
    cap = max(1, int(max_datasets or 0))
    cap = min(cap, 5000)
    rows = (
        db.query(Dataset.id)
        .filter(Dataset.tenant_id == tenant_id)
        .order_by(Dataset.updated_at.desc(), Dataset.created_at.desc(), Dataset.id.asc())
        .limit(cap)
        .all()
    )
    out: list[UUID] = []
    for r in rows:
        ds_id = r[0] if isinstance(r, tuple) and r else None
        if isinstance(ds_id, UUID):
            out.append(ds_id)
    return out


def _list_dataset_ids_for_drift_audit(
    db: Session,
    *,
    tenant_id: UUID,
    max_datasets: int,
) -> list[UUID]:
    cap = max(1, int(max_datasets or 0))
    cap = min(cap, 5000)

    # Prefer datasets that have recently-updated suites.
    rows = (
        db.query(EvidenceSuite.dataset_id, func.max(EvidenceSuite.updated_at))
        .filter(EvidenceSuite.tenant_id == tenant_id, EvidenceSuite.archived_at.is_(None))
        .group_by(EvidenceSuite.dataset_id)
        .order_by(func.max(EvidenceSuite.updated_at).desc())  # type: ignore[arg-type]
        .limit(cap)
        .all()
    )
    out: list[UUID] = []
    for dataset_id, _last in rows:
        if isinstance(dataset_id, UUID):
            out.append(dataset_id)
    return out


def _run_dataset_evidence_drift_audit(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    include_archived_items: bool,
    include_details: bool,
    details_limit: int,
    slice_top_n: int,
    max_items: int = 10_000,
) -> dict[str, Any]:
    suite_ids = [
        row[0]
        for row in (
            db.query(EvidenceSuite.id)
            .filter(EvidenceSuite.tenant_id == tenant_id, EvidenceSuite.dataset_id == dataset_id, EvidenceSuite.archived_at.is_(None))
            .all()
        )
        if row and row[0] is not None
    ]
    if not suite_ids:
        return {
            "dataset_id": str(dataset_id),
            "total_items": 0,
            "total_references": 0,
            "ok_references": 0,
            "drift_references": 0,
            "drift_rate": 0.0,
            "reasons": {},
            "details_truncated": False,
        }

    cap_items = max(1, int(max_items or 0))
    cap_items = min(cap_items, 50_000)

    q = db.query(EvidenceItem).filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id.in_(suite_ids))
    if not include_archived_items:
        q = q.filter(EvidenceItem.status != "archived")
    items = q.order_by(EvidenceItem.updated_at.desc()).limit(cap_items).all()

    audit = audit_reference_sources_drift(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        suite_id=None,
        suite_dataset_id=dataset_id,
        items=items,
        include_details=bool(include_details),
        details_limit=int(details_limit or 0),
        slice_top_n=int(slice_top_n or 0),
    )

    return {
        "dataset_id": str(audit.dataset_id),
        "total_items": int(audit.total_items),
        "total_references": int(audit.total_references),
        "ok_references": int(audit.ok_references),
        "drift_references": int(audit.drift_references),
        "drift_rate": float(audit.drift_rate),
        "reasons": dict(audit.reasons or {}),
        "details_truncated": bool(audit.details_truncated),
    }


def run_daily_index_audit_report(
    db: Session,
    *,
    tenant_id: UUID,
    execute: bool,
    force: bool = False,
    dataset_ids: list[UUID] | None = None,
    max_datasets: int = 50,
    max_check_ids: int = 5000,
    milvus_list_limit: int = 2000,
    sample_limit: int = 20,
    actor_id: str | None = SYSTEM_PERIODIC_AUDIT_ACTOR_ID,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Generate a bounded, dataset-scoped index-audit summary for one tenant.

    If execute=True, writes exactly one audit log entry per tenant per day (unless --force).
    """
    now0 = now or datetime.now(UTC)
    report_date = now0.date().isoformat()

    if bool(execute) and (not bool(force)) and _audit_already_written(
        db,
        tenant_id=tenant_id,
        action="observability.index_audit.daily",
        resource_type="index_audit_report",
        report_date=report_date,
    ):
        return {
            "tenant_id": str(tenant_id),
            "report_date": report_date,
            "ran_at": _dt_to_json(now0),
            "ok": True,
            "skipped": True,
            "skip_reason": "already_written",
        }

    try:
        cap_ds = max(1, int(max_datasets or 0))
    except Exception:
        cap_ds = 50
    cap_ds = min(cap_ds, 5000)

    ds_ids = list(dataset_ids or [])
    if not ds_ids:
        ds_ids = _list_dataset_ids_for_index_audit(db, tenant_id=tenant_id, max_datasets=cap_ds)
    ds_ids = ds_ids[:cap_ds]

    scanned = 0
    datasets_with_issues = 0
    vector_id_missing_total = 0
    vector_missing_backend_total = 0
    milvus_orphan_ids_total = 0

    errors: list[dict[str, Any]] = []
    per_dataset: list[dict[str, Any]] = []

    for ds_id in ds_ids:
        try:
            res = run_dataset_index_audit_internal(
                db=db,
                tenant_id=tenant_id,
                dataset_id=ds_id,
                max_check_ids=int(max_check_ids or 0),
                milvus_list_limit=int(milvus_list_limit or 0),
                sample_limit=int(sample_limit or 0),
            )
        except Exception as exc:  # noqa: BLE001
            if len(errors) < 20:
                errors.append({"dataset_id": str(ds_id), "error": str(type(exc).__name__)})
            continue

        scanned += 1
        vid_missing = int(res.get("vector_id_missing") or 0)
        missing_backend = int(res.get("vector_ids_missing_in_backend") or 0)
        orphan_ids = res.get("milvus_orphan_ids_sample") or []
        orphan_cnt = len(orphan_ids) if isinstance(orphan_ids, list) else 0

        vector_id_missing_total += max(0, vid_missing)
        vector_missing_backend_total += max(0, missing_backend)
        milvus_orphan_ids_total += max(0, orphan_cnt)

        has_issue = (vid_missing > 0) or (missing_backend > 0) or (orphan_cnt > 0)
        if has_issue:
            datasets_with_issues += 1

        per_dataset.append(
            {
                "dataset_id": str(res.get("dataset_id") or ds_id),
                "active_documents": int(res.get("active_documents") or 0),
                "active_chunks": int(res.get("active_chunks") or 0),
                "vector_id_missing": int(vid_missing),
                "vector_ids_missing_in_backend": int(missing_backend),
                "milvus_orphan_ids_sampled": int(orphan_cnt),
                # Keep bounded id samples (PII-safe; ids only).
                "vector_ids_missing_in_backend_sample": list(res.get("vector_ids_missing_in_backend_sample") or [])[:20],
                "milvus_orphan_ids_sample": list(orphan_ids)[:20],
            }
        )

    # Rank datasets by "issue severity" to keep the payload bounded but useful.
    def _severity(d: dict[str, Any]) -> tuple[int, int, int, str]:
        return (
            int(d.get("vector_ids_missing_in_backend") or 0),
            int(d.get("vector_id_missing") or 0),
            int(d.get("milvus_orphan_ids_sampled") or 0),
            str(d.get("dataset_id") or ""),
        )

    top_issue_datasets = sorted((d for d in per_dataset if _severity(d)[:3] != (0, 0, 0)), key=_severity, reverse=True)[:50]

    summary: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "report_date": report_date,
        "ran_at": _dt_to_json(now0),
        "max_datasets": int(cap_ds),
        "max_check_ids": int(max_check_ids or 0),
        "milvus_list_limit": int(milvus_list_limit or 0),
        "sample_limit": int(sample_limit or 0),
        "scanned_datasets": int(scanned),
        "datasets_with_issues": int(datasets_with_issues),
        "vector_id_missing_total": int(vector_id_missing_total),
        "vector_ids_missing_in_backend_total": int(vector_missing_backend_total),
        "milvus_orphan_ids_sampled_total": int(milvus_orphan_ids_total),
        "top_issue_datasets": list(top_issue_datasets),
        "errors_sample": list(errors),
        "ok": True,
        "skipped": False,
    }

    if not bool(execute):
        summary["dry_run"] = True
        return summary

    # Best-effort audit log write (PII-safe; small + bounded).
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="observability.index_audit.daily",
            resource_type="index_audit_report",
            resource_id=report_date,
            details={k: v for k, v in summary.items() if k not in {"ok"}},
        )
        db.commit()
        summary["dry_run"] = False
        return summary
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug("Ignoring non-critical periodic audit fallback failure: %s", exc)
        summary["ok"] = False
        summary["dry_run"] = False
        summary["audit_write_error"] = True
        return summary


def run_daily_embedding_drift_report(
    db: Session,
    *,
    tenant_id: UUID,
    execute: bool,
    force: bool = False,
    dataset_id: UUID | None = None,
    document_id: UUID | None = None,
    sample_n: int = 200,
    drift_threshold: float = 0.05,
    actor_id: str | None = "system:periodic_audit",
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Generate a bounded embedding drift snapshot summary for one tenant.

    If execute=True, writes exactly one audit log entry per tenant per day (unless --force).
    """
    now0 = now or datetime.now(UTC)
    report_date = now0.date().isoformat()

    if bool(execute) and (not bool(force)) and _audit_already_written(
        db,
        tenant_id=tenant_id,
        action="observability.embedding_drift.daily",
        resource_type="embedding_drift_report",
        report_date=report_date,
    ):
        return {
            "tenant_id": str(tenant_id),
            "report_date": report_date,
            "ran_at": _dt_to_json(now0),
            "ok": True,
            "skipped": True,
            "skip_reason": "already_written",
        }

    try:
        snap = run_embedding_drift_monitor(
            db=db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            sample_n=int(sample_n or 0),
            drift_threshold=float(drift_threshold),
        )
    except Exception:  # noqa: BLE001
        snap = {
            "schema": "mimirq.embedding_drift_snapshot.v1",
            "ok": False,
            "error": "snapshot_failed",
        }

    summary: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "report_date": report_date,
        "ran_at": _dt_to_json(now0),
        "ok": bool(snap.get("ok") is True),
        "skipped": False,
        "schema": str(snap.get("schema") or "mimirq.embedding_drift_snapshot.v1"),
        "vector_backend": snap.get("vector_backend"),
        "current_embedding_space_hash": snap.get("current_embedding_space_hash"),
        "sample_n_requested": snap.get("sample_n_requested"),
        "sample_n_used": snap.get("sample_n_used"),
        "sampled_items": snap.get("sampled_items"),
        "threshold": snap.get("threshold"),
        "missing_vectors": snap.get("missing_vectors"),
        "dim_mismatch": snap.get("dim_mismatch"),
        "drift": snap.get("drift"),
        "above_threshold": snap.get("above_threshold"),
        "stored_embedding_space_hash_counts": snap.get("stored_embedding_space_hash_counts"),
        "error": snap.get("error"),
        "scope": snap.get("scope"),
    }

    if not bool(execute):
        summary["dry_run"] = True
        return summary

    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="observability.embedding_drift.daily",
            resource_type="embedding_drift_report",
            resource_id=report_date,
            details={k: v for k, v in summary.items() if k not in {"ok"}},
        )
        db.commit()
        summary["dry_run"] = False
        return summary
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug("Ignoring non-critical periodic audit fallback failure: %s", exc)
        summary["ok"] = False
        summary["dry_run"] = False
        summary["audit_write_error"] = True
        return summary


def run_daily_evidence_drift_audit_report(
    db: Session,
    *,
    tenant_id: UUID,
    execute: bool,
    force: bool = False,
    dataset_ids: list[UUID] | None = None,
    max_datasets: int = 50,
    include_archived_items: bool = False,
    include_details: bool = False,
    details_limit: int = 0,
    slice_top_n: int = 20,
    actor_id: str | None = SYSTEM_PERIODIC_AUDIT_ACTOR_ID,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Generate a bounded evidence drift audit summary for one tenant.

    If execute=True, writes exactly one audit log entry per tenant per day (unless --force).
    """
    now0 = now or datetime.now(UTC)
    report_date = now0.date().isoformat()

    if bool(execute) and (not bool(force)) and _audit_already_written(
        db,
        tenant_id=tenant_id,
        action="evidence.drift_audit.daily",
        resource_type="evidence_drift_report",
        report_date=report_date,
    ):
        return {
            "tenant_id": str(tenant_id),
            "report_date": report_date,
            "ran_at": _dt_to_json(now0),
            "ok": True,
            "skipped": True,
            "skip_reason": "already_written",
        }

    try:
        cap_ds = max(1, int(max_datasets or 0))
    except Exception:
        cap_ds = 50
    cap_ds = min(cap_ds, 5000)

    ds_ids = list(dataset_ids or [])
    if not ds_ids:
        ds_ids = _list_dataset_ids_for_drift_audit(db, tenant_id=tenant_id, max_datasets=cap_ds)
    ds_ids = ds_ids[:cap_ds]

    scanned = 0
    total_items = 0
    total_refs = 0
    ok_refs = 0
    drift_refs = 0
    reasons: Counter[str] = Counter()

    errors: list[dict[str, Any]] = []
    per_dataset: list[dict[str, Any]] = []

    for ds_id in ds_ids:
        try:
            res = _run_dataset_evidence_drift_audit(
                db,
                tenant_id=tenant_id,
                dataset_id=ds_id,
                include_archived_items=bool(include_archived_items),
                include_details=bool(include_details),
                details_limit=int(details_limit or 0),
                slice_top_n=int(slice_top_n or 0),
            )
        except Exception as exc:  # noqa: BLE001
            if len(errors) < 20:
                errors.append({"dataset_id": str(ds_id), "error": str(type(exc).__name__)})
            continue

        scanned += 1
        ti = int(res.get("total_items") or 0)
        tr = int(res.get("total_references") or 0)
        okr = int(res.get("ok_references") or 0)
        dr = int(res.get("drift_references") or 0)
        total_items += max(0, ti)
        total_refs += max(0, tr)
        ok_refs += max(0, okr)
        drift_refs += max(0, dr)

        rs = res.get("reasons") if isinstance(res.get("reasons"), dict) else {}
        reasons.update({str(k): int(v or 0) for k, v in rs.items()})

        per_dataset.append(
            {
                "dataset_id": str(res.get("dataset_id") or ds_id),
                "total_items": int(ti),
                "total_references": int(tr),
                "drift_references": int(dr),
                "drift_rate": float(res.get("drift_rate") or 0.0),
            }
        )

    overall_drift_rate = round((drift_refs / total_refs), 6) if total_refs > 0 else 0.0

    top_drift_datasets = sorted(per_dataset, key=lambda d: (-float(d.get("drift_rate") or 0.0), -int(d.get("drift_references") or 0), str(d.get("dataset_id") or "")))[:50]

    summary: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "report_date": report_date,
        "ran_at": _dt_to_json(now0),
        "max_datasets": int(cap_ds),
        "include_archived_items": bool(include_archived_items),
        "include_details": bool(include_details),
        "details_limit": int(details_limit or 0),
        "slice_top_n": int(slice_top_n or 0),
        "scanned_datasets": int(scanned),
        "total_items": int(total_items),
        "total_references": int(total_refs),
        "ok_references": int(ok_refs),
        "drift_references": int(drift_refs),
        "drift_rate": float(overall_drift_rate),
        "reasons": _bounded_top_counts(reasons, max_items=50),
        "top_drift_datasets": list(top_drift_datasets),
        "errors_sample": list(errors),
        "ok": True,
        "skipped": False,
    }

    if not bool(execute):
        summary["dry_run"] = True
        return summary

    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="evidence.drift_audit.daily",
            resource_type="evidence_drift_report",
            resource_id=report_date,
            details={k: v for k, v in summary.items() if k not in {"ok"}},
        )
        db.commit()
        summary["dry_run"] = False
        return summary
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug("Ignoring non-critical periodic audit fallback failure: %s", exc)
        summary["ok"] = False
        summary["dry_run"] = False
        summary["audit_write_error"] = True
        return summary


def run_daily_access_review_summary(
    db: Session,
    *,
    tenant_id: UUID,
    execute: bool,
    force: bool = False,
    actor_id: str | None = SYSTEM_PERIODIC_AUDIT_ACTOR_ID,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Generate a bounded, PII-safe access review summary for one tenant.

    If execute=True, writes exactly one audit log entry per tenant per day (unless --force).

    The payload is intentionally small: counts + ids only (no document content).
    """
    now0 = now or datetime.now(UTC)
    report_date = now0.date().isoformat()

    if bool(execute) and (not bool(force)) and _audit_already_written(
        db,
        tenant_id=tenant_id,
        action="compliance.access_review.daily",
        resource_type="access_review_summary",
        report_date=report_date,
    ):
        return {
            "tenant_id": str(tenant_id),
            "report_date": report_date,
            "ran_at": _dt_to_json(now0),
            "ok": True,
            "skipped": True,
            "skip_reason": "already_written",
        }

    try:
        group_count = int(db.query(TenantGroup).filter(TenantGroup.tenant_id == tenant_id).count())
        group_member_count = int(db.query(TenantGroupMember).filter(TenantGroupMember.tenant_id == tenant_id).count())

        dataset_count = int(db.query(Dataset).filter(Dataset.tenant_id == tenant_id).count())
        dataset_permission_counts = {
            "all_team_members": int(
                db.query(Dataset)
                .filter(Dataset.tenant_id == tenant_id, Dataset.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS)
                .count()
            ),
            "only_me": int(
                db.query(Dataset)
                .filter(Dataset.tenant_id == tenant_id, Dataset.permission == DatasetPermissionEnum.ONLY_ME)
                .count()
            ),
            "partial_members": int(
                db.query(Dataset)
                .filter(Dataset.tenant_id == tenant_id, Dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS)
                .count()
            ),
        }

        dataset_member_allowlist_count = int(db.query(DatasetPermission).filter(DatasetPermission.tenant_id == tenant_id).count())
        dataset_group_allowlist_count = int(
            db.query(DatasetGroupPermission).filter(DatasetGroupPermission.tenant_id == tenant_id).count()
        )

        document_count = int(db.query(Document).filter(Document.tenant_id == tenant_id).count())
        doc_inherit_count = int(
            db.query(Document)
            .filter(
                Document.tenant_id == tenant_id,
                or_(
                    Document.access_mode == None,  # noqa: E711
                    Document.access_mode == "",
                    Document.access_mode == "inherit",
                ),
            )
            .count()
        )
        doc_partial_count = int(
            db.query(Document).filter(Document.tenant_id == tenant_id, Document.access_mode == "partial_members").count()
        )
        doc_only_me_count = int(
            db.query(Document).filter(Document.tenant_id == tenant_id, Document.access_mode == "only_me").count()
        )
        doc_all_team_count = int(
            db.query(Document).filter(Document.tenant_id == tenant_id, Document.access_mode == "all_team_members").count()
        )
        doc_known = doc_inherit_count + doc_partial_count + doc_only_me_count + doc_all_team_count
        doc_unknown_count = max(0, int(document_count - doc_known))
        document_access_mode_counts = {
            "inherit": int(doc_inherit_count),
            "partial_members": int(doc_partial_count),
            "only_me": int(doc_only_me_count),
            "all_team_members": int(doc_all_team_count),
            "unknown": int(doc_unknown_count),
        }

        document_member_allowlist_count = int(
            db.query(DocumentPermission).filter(DocumentPermission.tenant_id == tenant_id).count()
        )
        document_group_allowlist_count = int(
            db.query(DocumentGroupPermission).filter(DocumentGroupPermission.tenant_id == tenant_id).count()
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "tenant_id": str(tenant_id),
            "report_date": report_date,
            "ran_at": _dt_to_json(now0),
            "ok": False,
            "skipped": False,
            "error": str(exc)[:200],
        }

    summary: dict[str, Any] = {
        "schema": "mimirq.access_review_daily.v1",
        "tenant_id": str(tenant_id),
        "report_date": report_date,
        "ran_at": _dt_to_json(now0),
        "group_count": int(group_count),
        "group_member_count": int(group_member_count),
        "dataset_count": int(dataset_count),
        "dataset_permission_counts": dict(dataset_permission_counts),
        "dataset_member_allowlist_count": int(dataset_member_allowlist_count),
        "dataset_group_allowlist_count": int(dataset_group_allowlist_count),
        "document_count": int(document_count),
        "document_access_mode_counts": dict(document_access_mode_counts),
        "document_member_allowlist_count": int(document_member_allowlist_count),
        "document_group_allowlist_count": int(document_group_allowlist_count),
        "ok": True,
        "skipped": False,
    }

    if not bool(execute):
        summary["dry_run"] = True
        return summary

    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="compliance.access_review.daily",
            resource_type="access_review_summary",
            resource_id=report_date,
            details={k: v for k, v in summary.items() if k not in {"ok"}},
        )
        db.commit()
        summary["dry_run"] = False
        return summary
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug("Ignoring non-critical periodic audit fallback failure: %s", exc)
        summary["ok"] = False
        summary["dry_run"] = False
        summary["audit_write_error"] = True
        return summary


__all__ = [
    "run_daily_evidence_drift_audit_report",
    "run_daily_access_review_summary",
    "run_daily_index_audit_report",
    "run_daily_embedding_drift_report",
]
