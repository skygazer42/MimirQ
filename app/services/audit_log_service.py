"""
Audit log service.

Best-effort, fail-open: logging must never break product flows.
"""


import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def _hash_text(text: str) -> str:
    """Stable short hash for potentially sensitive strings (PII-minimal)."""
    raw = (text or "").encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()[:16]


def audit_log_event(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: str | None,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    request_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """
    Append an audit log record to the current DB transaction (no commit here).

    Callers should:
    - avoid storing raw message/content (use *_hash fields instead)
    - keep details small (a few KB at most)
    """
    try:
        item = AuditLog(
            tenant_id=tenant_id,
            actor_id=str(actor_id) if actor_id is not None else None,
            action=str(action or "")[:128],
            resource_type=str(resource_type)[:64] if resource_type else None,
            resource_id=str(resource_id)[:255] if resource_id else None,
            request_id=str(request_id)[:128] if request_id else None,
            ip=str(ip)[:64] if ip else None,
            user_agent=str(user_agent)[:512] if user_agent else None,
            details=dict(details or {}),
        )
        db.add(item)
    except Exception:
        # Never block product flows due to audit logging.
        return


def build_chat_audit_details(
    *,
    question: str,
    document_count: int,
    dataset_id: UUID | None,
    cache_hit: bool | None = None,
) -> dict[str, Any]:
    """Small, PII-minimal chat detail payload."""
    out: dict[str, Any] = {
        "question_hash": _hash_text((question or "").strip()),
        "question_chars": len((question or "").strip()),
        "document_count": int(document_count or 0),
        "dataset_id": str(dataset_id) if dataset_id else None,
    }
    if cache_hit is not None:
        out["cache_hit"] = bool(cache_hit)
    return out
