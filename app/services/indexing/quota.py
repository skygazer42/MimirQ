"""Owned quota operations for indexing."""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document as DBDocument
from app.services.indexing.tracking import _INDEXER_FALLBACK_LOG_MESSAGE
from app.services.metrics_logger import log_metrics

logger = logging.getLogger("indexer")

_INGEST_GATE_ACTION = "document.ingest_gate"


def _tenant_quota_fail_closed_enabled() -> bool:
    return settings.TENANT_QUOTA_FAIL_CLOSED


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _record_ingest_gate_outcome(
    metadata: dict[str, Any] | None,
    *,
    gate: str,
    outcome: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(metadata or {})
    gates = out.get("ingest_gate_outcomes")
    gates = dict(gates) if isinstance(gates, dict) else {}
    entry: dict[str, Any] = {
        "gate": str(gate or "").strip() or "unknown",
        "outcome": str(outcome or "").strip() or "degraded",
        "reason": str(reason or "").strip() or "unknown",
        "recorded_at": _now_iso(),
    }
    if isinstance(details, dict):
        for key, value in details.items():
            if value not in (None, "", [], {}):
                entry[str(key)] = value
    gates[entry["gate"]] = entry
    out["ingest_gate_outcomes"] = gates
    return out


def _audit_ingest_gate_event(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    gate: str,
    outcome: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> None:
    try:
        from app.services.audit_log_service import audit_log_event

        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=None,
            action=_INGEST_GATE_ACTION,
            resource_type="document",
            resource_id=str(document_id),
            details={
                "gate": str(gate or "").strip() or "unknown",
                "outcome": str(outcome or "").strip() or "degraded",
                "reason": str(reason or "").strip() or "unknown",
                **(dict(details or {}) if isinstance(details, dict) else {}),
            },
        )
    except Exception as exc:
        logger.debug(_INDEXER_FALLBACK_LOG_MESSAGE, exc)


def _persist_ingest_gate_outcome_best_effort(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    gate: str,
    outcome: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> None:
    try:
        db_document = (
            db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id, DBDocument.id == document_id).first()
        )
        if db_document is not None:
            db_document.doc_metadata = _record_ingest_gate_outcome(
                dict(db_document.doc_metadata or {}),
                gate=gate,
                outcome=outcome,
                reason=reason,
                details=details,
            )
    except Exception as exc:
        logger.debug(_INDEXER_FALLBACK_LOG_MESSAGE, exc)


def _enforce_embedding_quota_gate(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    additional_chars: int,
) -> dict[str, Any]:
    from app.services.tenant_quota_service import (
        TenantQuotaExceededError,
        enforce_tenant_embedding_char_quota,
    )

    try:
        return enforce_tenant_embedding_char_quota(
            db,
            tenant_id=tenant_id,
            additional_chars=int(additional_chars or 0),
        )
    except TenantQuotaExceededError:
        raise
    except Exception as exc:
        closed = _tenant_quota_fail_closed_enabled()
        outcome = "closed" if closed else "degraded"
        reason = "tenant_quota_gate_unavailable"
        details = {
            "quota": "embedding_chars",
            "additional_chars": max(0, int(additional_chars or 0)),
            "error": str(exc)[:200],
            "fail_closed": bool(closed),
        }
        log_metrics(
            {
                "event": "ingest.quota_gate",
                "tenant_id": str(tenant_id),
                "document_id": str(document_id),
                "quota": "embedding_chars",
                "outcome": outcome,
                "reason": reason,
                "fail_closed": bool(closed),
            }
        )
        _persist_ingest_gate_outcome_best_effort(
            db,
            tenant_id=tenant_id,
            document_id=document_id,
            gate="tenant_quota",
            outcome=outcome,
            reason=reason,
            details=details,
        )
        _audit_ingest_gate_event(
            db,
            tenant_id=tenant_id,
            document_id=document_id,
            gate="tenant_quota",
            outcome=outcome,
            reason=reason,
            details=details,
        )
        if closed:
            raise TenantQuotaExceededError(
                "embedding_chars_gate_unavailable",
                "Tenant embedding quota enforcement unavailable",
                meta={
                    **details,
                    "outcome": outcome,
                    "reason": reason,
                },
            ) from exc
        logger.warning("Tenant quota check degraded during indexing; continuing fail-open: %s", str(exc)[:200])
        return {
            "enabled": False,
            "mode": "warn",
            "limit_chars": 0,
            "used_chars": 0,
            "additional_chars": max(0, int(additional_chars or 0)),
            "would_exceed": False,
            "gate_outcome": outcome,
            "gate_reason": reason,
        }
