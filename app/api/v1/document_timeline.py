import uuid
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document_timeline import DocumentTimelineItem, DocumentTimelineResponse
from app.core.database import get_db
from app.models.audit_log import AuditLog
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.services.dataset_service import DatasetService
from app.services.document_access_service import assert_document_acl_readable

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

DOC_NOT_FOUND_DETAIL = "Document not found"

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

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
        key_norm = str(key or "").strip()
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


@router.get(
    "/{document_id}/timeline", response_model=DocumentTimelineResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
def get_document_timeline(
    document_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """User-facing document timeline (audit logs + synthetic document state events)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    document = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    dataset: Dataset | None = None
    if document.dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
    assert_document_acl_readable(db, tenant_id=tenant_id, account_id=account_id, document=document, dataset=dataset)

    audit_rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.tenant_id == tenant_id,
            AuditLog.resource_type == "document",
            AuditLog.resource_id == str(document_id),
        )
        .order_by(desc(AuditLog.created_at), desc(AuditLog.id))
        .limit(int(limit or 200))
        .all()
    )

    items: list[DocumentTimelineItem] = []

    created_at = getattr(document, "created_at", None)
    if created_at is not None:
        items.append(
            DocumentTimelineItem(
                id=f"synthetic:created:{document_id}",
                action="document.created",
                created_at=created_at,
                source="synthetic",
                actor_id=(getattr(document, "owner_id", None) or None),
                stage=(getattr(document, "current_stage", None) or None),
                status=(str(getattr(document, "status", "") or "").strip() or None),
                progress=int(getattr(document, "processing_progress", 0) or 0),
            )
        )

    updated_at = getattr(document, "updated_at", None)
    if updated_at is not None and (created_at is None or updated_at != created_at):
        items.append(
            DocumentTimelineItem(
                id=f"synthetic:status:{document_id}",
                action="document.status",
                created_at=updated_at,
                source="synthetic",
                stage=(getattr(document, "current_stage", None) or None),
                status=(str(getattr(document, "status", "") or "").strip() or None),
                progress=int(getattr(document, "processing_progress", 0) or 0),
            )
        )

    for row in audit_rows:
        raw_details = getattr(row, "details", None)
        safe_details = _sanitize_timeline_details(raw_details)

        stage = safe_details.get("stage") if isinstance(safe_details.get("stage"), str) else None
        status = safe_details.get("status") if isinstance(safe_details.get("status"), str) else None
        progress_val = safe_details.get("progress")
        progress = int(progress_val) if isinstance(progress_val, (int, float)) else None

        items.append(
            DocumentTimelineItem(
                id=str(getattr(row, "id", "") or ""),
                action=str(getattr(row, "action", "") or ""),
                created_at=getattr(row, "created_at", None),
                source="audit",
                actor_id=(getattr(row, "actor_id", None) or None),
                request_id=(getattr(row, "request_id", None) or None),
                stage=stage,
                status=status,
                progress=progress,
                details=safe_details,
            )
        )

    def _dt_ts(value: Any) -> float:
        try:
            return float(value.timestamp()) if value is not None else 0.0
        except Exception:
            return 0.0

    items.sort(key=lambda item: (_dt_ts(item.created_at), str(item.id)), reverse=True)
    items = items[: int(limit or 200)]

    return DocumentTimelineResponse(total=len(items), items=items)
