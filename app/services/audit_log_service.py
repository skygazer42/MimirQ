"""
Audit log service.

Best-effort, fail-open: logging must never break product flows.
"""

import hashlib
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Query, Session

from app.models.audit_log import AuditLog


def apply_audit_log_filters(
    q: Query,
    *,
    actor_id: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    request_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Query:
    if actor_id:
        q = q.filter(AuditLog.actor_id == actor_id)
    if action:
        q = q.filter(AuditLog.action == action)
    if resource_type:
        q = q.filter(AuditLog.resource_type == resource_type)
    if resource_id:
        q = q.filter(AuditLog.resource_id == resource_id)
    if request_id:
        q = q.filter(AuditLog.request_id == request_id)
    if since is not None:
        q = q.filter(AuditLog.created_at >= since)
    if until is not None:
        q = q.filter(AuditLog.created_at <= until)
    return q


def _hash_text(text: str) -> str:
    """Stable short hash for potentially sensitive strings (PII-minimal)."""
    raw = text.encode("utf-8", "ignore")
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
            action=action[:128],
            resource_type=str(resource_type)[:64] if resource_type is not None else None,
            resource_id=str(resource_id)[:255] if resource_id is not None else None,
            request_id=str(request_id)[:128] if request_id is not None else None,
            ip=str(ip)[:64] if ip is not None else None,
            user_agent=str(user_agent)[:512] if user_agent is not None else None,
            details=dict(details) if details is not None else {},
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
    question = question.strip()
    out: dict[str, Any] = {
        "question_hash": _hash_text(question),
        "question_chars": len(question),
        "document_count": document_count,
        "dataset_id": str(dataset_id) if dataset_id else None,
    }
    if cache_hit is not None:
        out["cache_hit"] = cache_hit
    return out
