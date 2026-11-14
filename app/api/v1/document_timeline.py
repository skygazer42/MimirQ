from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import DocumentTimelineItem, DocumentTimelineQuery, DocumentTimelineResponse
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.services import dataset_service
from app.services.document_access_service import assert_document_readable_for_lifecycle

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)

_TIMELINE_REDACT_KEYS = {
    "content",
    "text",
    "markdown",
    "html",
    "raw",
    "prompt",
    "question",
    "answer",
    "secret",
    "token",
    "password",
    "api_key",
}
_TIMELINE_VALUE_SKIPPED = object()


def _sanitize_timeline_details(details: Any, *, _depth: int = 0) -> dict[str, Any]:
    """
    Best-effort PII-minimal details projection for user-facing timelines.

    Audit logs should already be small, but timeline is displayed broadly; keep it safe by default.
    """
    if not isinstance(details, dict) or _depth >= 3:
        return {}

    out: dict[str, Any] = {}
    for key, value in details.items():
        key_norm = str(key).strip()
        if not key_norm:
            continue
        key_l = key_norm.lower()
        if any(redact in key_l for redact in _TIMELINE_REDACT_KEYS):
            continue
        safe_value = _sanitize_timeline_value(value, depth=_depth)
        if safe_value is not _TIMELINE_VALUE_SKIPPED:
            out[key_norm] = safe_value
    return out


def _sanitize_timeline_value(value: Any, *, depth: int) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        safe_items: list[Any] = []
        for item in value[:20]:
            if isinstance(item, (str, int, float, bool)) or item is None:
                safe_items.append(item)
            elif isinstance(item, dict):
                safe_item = _sanitize_timeline_details(dict(list(item.items())[:20]), _depth=depth + 1)
                if safe_item:
                    safe_items.append(safe_item)
        return safe_items or _TIMELINE_VALUE_SKIPPED
    if isinstance(value, dict):
        safe_map = _sanitize_timeline_details(dict(list(value.items())[:20]), _depth=depth + 1)
        return safe_map or _TIMELINE_VALUE_SKIPPED
    return _TIMELINE_VALUE_SKIPPED


@router.get("/{document_id}/timeline", response_model=DocumentTimelineResponse)
def get_document_timeline(
    document_id: UUID,
    params: Annotated[DocumentTimelineQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentTimelineResponse:
    """User-facing document timeline (audit logs + synthetic document state events)."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    document = db.query(Document).filter(Document.id == document_id, Document.tenant_id == tenant_id).first()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    assert_document_readable_for_lifecycle(db, tenant_id=tenant_id, account_id=account_id, document=document)

    audit_rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.tenant_id == tenant_id,
            AuditLog.resource_type == "document",
            AuditLog.resource_id == str(document_id),
        )
        .order_by(desc(AuditLog.created_at), desc(AuditLog.id))
        .limit(params.limit)
        .all()
    )

    items: list[DocumentTimelineItem] = []

    created_at = document.created_at
    if created_at is not None:
        items.append(
            DocumentTimelineItem(
                id=f"synthetic:created:{document_id}",
                action="document.created",
                created_at=created_at,
                source="synthetic",
                actor_id=document.owner_id,
                stage=document.current_stage,
                status=document.status,
                progress=document.processing_progress,
            )
        )

    updated_at = document.updated_at
    if updated_at is not None and (created_at is None or updated_at != created_at):
        items.append(
            DocumentTimelineItem(
                id=f"synthetic:status:{document_id}",
                action="document.status",
                created_at=updated_at,
                source="synthetic",
                stage=document.current_stage,
                status=document.status,
                progress=document.processing_progress,
            )
        )

    for row in audit_rows:
        raw_details = row.details
        safe_details = _sanitize_timeline_details(raw_details)

        stage = safe_details.get("stage")
        status = safe_details.get("status")
        progress_val = safe_details.get("progress")
        progress = int(progress_val) if isinstance(progress_val, (int, float)) else None

        items.append(
            DocumentTimelineItem(
                id=str(row.id),
                action=row.action,
                created_at=row.created_at,
                source="audit",
                actor_id=row.actor_id,
                request_id=row.request_id,
                stage=stage if isinstance(stage, str) else None,
                status=status if isinstance(status, str) else None,
                progress=progress,
                details=safe_details,
            )
        )

    items.sort(key=_timeline_sort_key, reverse=True)
    items = items[: params.limit]

    return DocumentTimelineResponse(total=len(items), items=items)


def _timeline_sort_key(item: DocumentTimelineItem) -> tuple[float, str]:
    try:
        timestamp = item.created_at.timestamp()
    except (ValueError, OverflowError, OSError):
        timestamp = 0.0
    return timestamp, item.id
