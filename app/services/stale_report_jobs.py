"""
Stale report job helpers (ops / governance automation).

Purpose:
- Generate a bounded, PII-safe daily "staleness" summary for connector-created documents.
- Record the summary to audit logs (no raw content).

Design principles (similar to retention jobs):
- Bounded: callers provide max_documents
- Auditable: best-effort audit_log_event
- Fail-open: never crash the product due to reporting automation
"""

import contextlib
from collections import Counter
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.connector import ConnectorRun, ConnectorRunDocument
from app.models.document import Document as DBDocument
from app.rag.core.logging import get_logger
from app.services.audit_log_service import audit_log_event

logger = get_logger(__name__)


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


def _parse_datetime_best_effort(raw: object) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None

    # HTTP-date (e.g. Last-Modified) is common for URL-based connectors.
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception as exc:
        logger.debug("Ignoring invalid HTTP-date timestamp: %s", exc)

    # ISO timestamps (e.g. connector metadata) are also common.
    try:
        iso = value[:-1] + "+00:00" if value.endswith("Z") else value
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def _bounded_top_counts(counter: Counter[str], *, max_items: int) -> dict[str, int]:
    out: dict[str, int] = {}
    for k, v in counter.most_common(max(0, int(max_items or 0))):
        out[str(k)] = int(v)
    return out


def _audit_already_written(db: Session, *, tenant_id: UUID, action: str, report_date: str) -> bool:
    try:
        row = (
            db.query(AuditLog.id)
            .filter(
                AuditLog.tenant_id == tenant_id,
                AuditLog.action == str(action),
                AuditLog.resource_type == "stale_report",
                AuditLog.resource_id == str(report_date),
            )
            .limit(1)
            .first()
        )
        return bool(row)
    except Exception:
        return False


def _list_connector_document_rows(
    db: Session,
    *,
    tenant_id: UUID,
    cutoff: datetime,
    max_documents: int,
) -> list[dict[str, Any]]:
    """
    List candidate connector-created documents for staleness reporting.

    Notes:
    - Uses a conservative pre-filter on `documents.updated_at <= cutoff` to reduce work.
    - Returns a list of JSON-safe dict rows (bounded by max_documents).
    """
    max_docs = max(1, int(max_documents or 0))
    max_docs = min(max_docs, 50_000)

    q = (
        db.query(
            ConnectorRun.connector_id,
            ConnectorRun.dataset_id.label("run_dataset_id"),
            ConnectorRunDocument.document_id,
            ConnectorRunDocument.created_at.label("linked_at"),
            DBDocument.dataset_id.label("document_dataset_id"),
            DBDocument.status,
            DBDocument.created_at,
            DBDocument.updated_at,
            DBDocument.processed_at,
            DBDocument.doc_metadata,
        )
        .join(ConnectorRunDocument, ConnectorRunDocument.run_id == ConnectorRun.id)
        .join(DBDocument, DBDocument.id == ConnectorRunDocument.document_id)
        .filter(
            ConnectorRun.tenant_id == tenant_id,
            ConnectorRunDocument.tenant_id == tenant_id,
            DBDocument.tenant_id == tenant_id,
        )
        .filter(DBDocument.disabled_at.is_(None))
        .filter(DBDocument.updated_at <= cutoff)
        .order_by(DBDocument.updated_at.asc(), ConnectorRunDocument.created_at.asc())
        .limit(max_docs)
    )

    rows = q.all()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "connector_id": str(getattr(r, "connector_id", "") or ""),
                "run_dataset_id": getattr(r, "run_dataset_id", None),
                "document_id": getattr(r, "document_id", None),
                "linked_at": getattr(r, "linked_at", None),
                "document_dataset_id": getattr(r, "document_dataset_id", None),
                "status": str(getattr(r, "status", "") or ""),
                "created_at": getattr(r, "created_at", None),
                "updated_at": getattr(r, "updated_at", None),
                "processed_at": getattr(r, "processed_at", None),
                "doc_metadata": dict(getattr(r, "doc_metadata", None) or {}),
            }
        )
    return out


def run_daily_stale_report(
    db: Session,
    *,
    tenant_id: UUID,
    stale_after_days: int,
    max_documents: int,
    execute: bool,
    force: bool = False,
    actor_id: str | None = "system:stale_report",
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Generate a bounded stale summary for one tenant and optionally write an audit log entry.

    "Stale" definition (bounded, metadata-only):
    - For connector-created documents, compute an effective "source timestamp" in this order:
      1) metadata.source_last_modified_at (preferred; best-effort from HTTP header / connector metadata)
      2) metadata.source_fetched_at
      3) processed_at / updated_at / created_at / linked_at (fallback)
    - If effective timestamp is older than (now - stale_after_days), classify as stale.
    """
    now0 = now or datetime.now(UTC)
    try:
        days_i = max(1, int(stale_after_days or 0))
    except Exception:
        days_i = 30
    try:
        max_docs_i = max(1, int(max_documents or 0))
    except Exception:
        max_docs_i = 5000
    max_docs_i = min(max_docs_i, 50_000)

    report_date = now0.date().isoformat()
    cutoff = now0 - timedelta(days=int(days_i))

    if (
        bool(execute)
        and (not bool(force))
        and _audit_already_written(
            db, tenant_id=tenant_id, action="connectors.stale_report.daily", report_date=report_date
        )
    ):
        return {
            "tenant_id": str(tenant_id),
            "report_date": report_date,
            "ran_at": _dt_to_json(now0),
            "stale_after_days": int(days_i),
            "max_documents": int(max_docs_i),
            "ok": True,
            "skipped": True,
            "skip_reason": "already_written",
        }

    rows = _list_connector_document_rows(db, tenant_id=tenant_id, cutoff=cutoff, max_documents=max_docs_i)

    # Deduplicate by document_id (best-effort) in case a document appears in multiple connector runs.
    seen_doc_ids: set[str] = set()
    scanned = 0
    stale = 0

    stale_sample_ids: list[str] = []
    by_connector_scanned: Counter[str] = Counter()
    by_connector_stale: Counter[str] = Counter()
    by_dataset_stale: Counter[str] = Counter()
    by_source_kind: Counter[str] = Counter()
    by_reason: Counter[str] = Counter()
    age_buckets: Counter[str] = Counter()

    def _bucket_age_days(age_days: int) -> str:
        if age_days < 7:
            return "<7d"
        if age_days < 30:
            return "7-29d"
        if age_days < 90:
            return "30-89d"
        if age_days < 180:
            return "90-179d"
        return ">=180d"

    for row in rows:
        doc_id_raw = row.get("document_id")
        doc_id = str(doc_id_raw) if doc_id_raw is not None else ""
        if not doc_id or doc_id in seen_doc_ids:
            continue
        seen_doc_ids.add(doc_id)

        connector_id = str(row.get("connector_id") or "unknown").strip() or "unknown"
        by_connector_scanned[connector_id] += 1
        scanned += 1

        meta = row.get("doc_metadata") if isinstance(row.get("doc_metadata"), dict) else {}
        src_kind = str(meta.get("source_last_modified_source") or "").strip() or "unknown"
        by_source_kind[src_kind] += 1

        eff_dt = _parse_datetime_best_effort(meta.get("source_last_modified_at"))
        reason = "meta:source_last_modified_at"
        if eff_dt is None:
            eff_dt = _parse_datetime_best_effort(meta.get("source_fetched_at"))
            reason = "meta:source_fetched_at"
        if eff_dt is None:
            eff_dt = row.get("processed_at") or row.get("updated_at") or row.get("created_at") or row.get("linked_at")
            reason = "fallback:document_timestamps"
        if isinstance(eff_dt, datetime):
            if eff_dt.tzinfo is None:
                eff_dt = eff_dt.replace(tzinfo=UTC)
            eff_dt = eff_dt.astimezone(UTC)
        else:
            # Should be rare; treat as now to avoid false stale inflation.
            eff_dt = now0
            reason = "fallback:unknown"
        by_reason[reason] += 1

        age_days = int(max(0, (now0 - eff_dt).total_seconds() // 86400))
        age_buckets[_bucket_age_days(age_days)] += 1

        is_stale = eff_dt <= cutoff
        if not is_stale:
            continue

        stale += 1
        by_connector_stale[connector_id] += 1

        dataset_id = row.get("document_dataset_id") or row.get("run_dataset_id")
        if dataset_id is not None:
            by_dataset_stale[str(dataset_id)] += 1

        if len(stale_sample_ids) < 20:
            stale_sample_ids.append(doc_id)

    summary = {
        "tenant_id": str(tenant_id),
        "report_date": report_date,
        "ran_at": _dt_to_json(now0),
        "stale_after_days": int(days_i),
        "max_documents": int(max_docs_i),
        "scanned": int(scanned),
        "stale": int(stale),
        "by_connector_scanned": _bounded_top_counts(by_connector_scanned, max_items=50),
        "by_connector_stale": _bounded_top_counts(by_connector_stale, max_items=50),
        "by_dataset_stale": _bounded_top_counts(by_dataset_stale, max_items=50),
        "by_source_kind": _bounded_top_counts(by_source_kind, max_items=20),
        "by_reason": _bounded_top_counts(by_reason, max_items=20),
        "age_buckets": dict(age_buckets),
        "stale_sample_document_ids": list(stale_sample_ids),
        "ok": True,
        "skipped": False,
    }

    if not bool(execute):
        summary["dry_run"] = True
        return summary

    # Best-effort audit log write (PII-safe; no raw URLs/content).
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="connectors.stale_report.daily",
            resource_type="stale_report",
            resource_id=report_date,
            details={k: v for k, v in summary.items() if k not in {"ok"}},
        )
        db.commit()
        summary["dry_run"] = False
        return summary
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()
        summary["ok"] = False
        summary["error"] = "failed_to_write_audit"
        summary["dry_run"] = False
        return summary


__all__ = ["run_daily_stale_report"]
