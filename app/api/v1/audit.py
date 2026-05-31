"""
Audit log endpoints (admin-only).

This is intentionally minimal and PII-safe by default.
"""

from __future__ import annotations

import gzip as gzip_lib
import io
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, desc, or_
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.models.audit_log import AuditLog
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.document import Document, DocumentPermission
from app.models.group_permissions import DatasetGroupPermission, DocumentGroupPermission
from app.models.tenant_group import TenantGroup, TenantGroupMember
from app.rag.core.hashing import stable_hash
from app.rag.core.logging import get_logger
from app.services.audit_log_retention import (
    delete_audit_log_rows,
    plan_audit_log_purge,
    plan_filtered_audit_log_purge,
    purge_audit_log_rows,
    purge_filtered_audit_log_rows,
)
from app.services.audit_log_service import audit_log_event
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger(__name__)
_AUDIT_ROUTER_FALLBACK_LOG_MESSAGE = "Ignoring non-critical audit router fallback failure: %s"

_SENSITIVE_DETAIL_KEYS = {
    "sql",
    "sql_redacted",
    "connection",
    "dsn",
    "uri",
    "jdbc_url",
    "connection_string",
    "host",
    "hostname",
    "port",
    "database",
    "db",
    "username",
    "user",
    "password",
    "token",
    "cookie",
    "auth",
}


def _ensure_admin(db: Session, tenant_id: UUID, account_id: str) -> None:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.AUDIT_READ,
        detail="No permission to access audit logs",
    )


class AuditLogOut(BaseModel):
    id: UUID
    tenant_id: UUID
    actor_id: str | None = None
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    request_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    details: dict[str, Any] = {}
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditLogListResponse(BaseModel):
    total: int
    items: list[AuditLogOut]


class AuditLogPurgeResponse(BaseModel):
    dry_run: bool = True
    scope: str = "retention"
    retention_days: int
    cutoff: datetime
    max_delete: int
    eligible: int
    deleted: int
    filters: dict[str, Any] = Field(default_factory=dict)


class AuditLogDeleteRequest(BaseModel):
    ids: list[UUID] = Field(..., min_length=1, max_length=500)


class AuditLogDeleteResponse(BaseModel):
    requested: int
    deleted: int
    missing: int
    ids: list[UUID]


def _sanitize_details(details: dict[str, Any], *, include_sensitive: bool) -> dict[str, Any]:
    if include_sensitive or not isinstance(details, dict):
        return dict(details or {})
    out: dict[str, Any] = {}
    for key, value in (details or {}).items():
        lowered = str(key or "").strip().lower()
        if lowered in _SENSITIVE_DETAIL_KEYS:
            continue
        if isinstance(value, dict):
            out[key] = _sanitize_details(value, include_sensitive=False)
        else:
            out[key] = value
    return out


def _iter_gzip_chunks(chunks: Iterator[bytes], *, flush_bytes: int = 64 * 1024) -> Iterator[bytes]:
    """
    Streaming gzip wrapper for byte iterators.

    This keeps memory bounded and supports SIEM-style log shipping.
    """
    buffer = io.BytesIO()
    gz = gzip_lib.GzipFile(fileobj=buffer, mode="wb")
    try:
        for chunk in chunks:
            if not chunk:
                continue
            gz.write(chunk)
            if buffer.tell() >= int(flush_bytes or 64 * 1024):
                gz.flush()
                data = buffer.getvalue()
                if data:
                    yield data
                buffer.seek(0)
                buffer.truncate(0)
    finally:
        gz.close()
        data = buffer.getvalue()
        if data:
            yield data


def _dt_to_json(v: Any) -> str | None:
    """
    Serialize datetime-like objects for export-friendly JSON.

    We prefer the "Z" suffix for UTC to avoid "+" being interpreted as a space
    when callers reuse cursors in query strings.
    """
    if v is None:
        return None
    if not isinstance(v, datetime):
        return None
    try:
        s = v.isoformat()
    except Exception:
        return None
    if s.endswith("+00:00"):
        s = s[:-6] + "Z"
    return s


def _dedupe_uuids(values: list[UUID]) -> list[UUID]:
    return list(dict.fromkeys(values or []))


@router.get("/logs", response_model=AuditLogListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_audit_logs(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    actor_id: Annotated[str | None, Query(max_length=255)] = None,
    action: Annotated[str | None, Query(max_length=128)] = None,
    resource_type: Annotated[str | None, Query(max_length=64)] = None,
    resource_id: Annotated[str | None, Query(max_length=255)] = None,
    request_id: Annotated[str | None, Query(max_length=128)] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    include_sensitive: Annotated[bool, Query()] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_admin(db, tenant_id, account_id)

    q = db.query(AuditLog).filter(AuditLog.tenant_id == tenant_id)

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

    total = int(q.count())
    items = q.order_by(desc(AuditLog.created_at), desc(AuditLog.id)).offset(skip).limit(limit).all()
    payload: list[AuditLogOut] = []
    for item in items:
        obj = AuditLogOut.model_validate(item)
        obj.details = _sanitize_details(dict(obj.details or {}), include_sensitive=bool(include_sensitive))
        payload.append(obj)
    return {"total": total, "items": payload}


@router.get("/logs/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_audit_logs(
    limit: Annotated[int, Query(ge=1, le=10000)] = 1000,
    actor_id: Annotated[str | None, Query(max_length=255)] = None,
    action: Annotated[str | None, Query(max_length=128)] = None,
    resource_type: Annotated[str | None, Query(max_length=64)] = None,
    resource_id: Annotated[str | None, Query(max_length=255)] = None,
    request_id: Annotated[str | None, Query(max_length=128)] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    after_created_at: Annotated[datetime | None, Query(description='Cursor: last seen created_at')] = None,
    after_id: Annotated[UUID | None, Query(description='Cursor: last seen id (tie-breaker)')] = None,
    include_sensitive: Annotated[
        bool, Query(description='Include sensitive detail keys (admin/auditor only)')
    ] = False,
    gzip: Annotated[bool, Query(description='Return gzip-compressed NDJSON (Content-Encoding: gzip)')] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Export audit logs as NDJSON (JSON Lines) for SIEM ingestion.

    Notes:
    - Ordered ascending by (created_at, id) to support incremental exports.
    - Uses cursor params (after_created_at, after_id) for efficient resume.
    - Details are sanitized by default (include_sensitive=false).
    """
    _ensure_admin(db, tenant_id, account_id)

    q = db.query(AuditLog).filter(AuditLog.tenant_id == tenant_id)

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

    if after_created_at is not None:
        if after_id is not None:
            q = q.filter(
                or_(
                    AuditLog.created_at > after_created_at,
                    and_(AuditLog.created_at == after_created_at, AuditLog.id > after_id),
                )
            )
        else:
            q = q.filter(AuditLog.created_at > after_created_at)

    rows = q.order_by(AuditLog.created_at.asc(), AuditLog.id.asc()).limit(limit).all()

    def _iter_lines() -> Iterator[bytes]:
        for row in rows:
            obj = AuditLogOut.model_validate(row)
            obj.details = _sanitize_details(dict(obj.details or {}), include_sensitive=bool(include_sensitive))
            payload = obj.model_dump(mode="json")
            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
            yield line.encode("utf-8")

    body_iter: Iterator[bytes] = _iter_lines()
    headers = {
        "Cache-Control": "no-store",
    }
    if gzip:
        headers["Content-Encoding"] = "gzip"
        body_iter = _iter_gzip_chunks(body_iter)

    return StreamingResponse(
        body_iter,
        media_type="application/x-ndjson",
        headers=headers,
    )


@router.post("/logs/purge", response_model=AuditLogPurgeResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def purge_audit_logs(
    retention_days: Annotated[int, Query(ge=1, le=3650, description='Delete logs older than N days')] = 90,
    max_delete: Annotated[int, Query(ge=1, le=1000000, description='Max rows to delete in this call')] = 100_000,
    dry_run: Annotated[bool, Query(description='Plan only; do not delete rows')] = True,
    purge_scope: Annotated[
        Literal["retention", "filtered"],
        Query(description='retention=older than N days; filtered=current explicit filters'),
    ] = "retention",
    actor_id: Annotated[str | None, Query(max_length=255)] = None,
    action: Annotated[str | None, Query(max_length=128)] = None,
    resource_type: Annotated[str | None, Query(max_length=64)] = None,
    resource_id: Annotated[str | None, Query(max_length=255)] = None,
    request_id: Annotated[str | None, Query(max_length=128)] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Purge old audit logs for the current tenant (bounded).

    Security:
    - Admin-only (owner/admin). Auditors can read/export logs but cannot purge.
    """
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.AUDIT_MANAGE,
        detail="No permission to manage audit logs",
    )

    now = datetime.now(UTC)
    cutoff = now - timedelta(days=int(retention_days or 0))

    filter_payload: dict[str, Any] = {
        k: v
        for k, v in {
            "actor_id": actor_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "request_id": request_id,
            "since": since.isoformat() if since is not None else None,
            "until": until.isoformat() if until is not None else None,
        }.items()
        if v not in (None, "")
    }

    if purge_scope == "filtered" and not filter_payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one filter is required for filtered audit log purge",
        )

    if purge_scope == "filtered":
        eligible = int(
            plan_filtered_audit_log_purge(
                db,
                tenant_id=tenant_id,
                max_delete=int(max_delete or 0),
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                request_id=request_id,
                since=since,
                until=until,
            )
            or 0
        )
    else:
        eligible = int(plan_audit_log_purge(db, tenant_id=tenant_id, cutoff=cutoff, max_delete=int(max_delete or 0)) or 0)

    deleted = 0
    if not bool(dry_run):
        if purge_scope == "filtered":
            deleted = int(
                purge_filtered_audit_log_rows(
                    db,
                    tenant_id=tenant_id,
                    max_delete=int(max_delete or 0),
                    actor_id=actor_id,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    request_id=request_id,
                    since=since,
                    until=until,
                    commit=True,
                )
                or 0
            )
        else:
            deleted = int(
                purge_audit_log_rows(
                    db,
                    tenant_id=tenant_id,
                    cutoff=cutoff,
                    max_delete=int(max_delete or 0),
                    commit=True,
                )
                or 0
            )

    # Best-effort: record the purge operation itself (small, PII-safe).
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="audit.logs.purge",
            resource_type="audit_logs",
            resource_id=None,
            details={
                "dry_run": bool(dry_run),
                "purge_scope": str(purge_scope),
                "retention_days": int(retention_days or 0),
                "cutoff": cutoff.isoformat(),
                "max_delete": int(max_delete or 0),
                "eligible": int(eligible or 0),
                "deleted": int(deleted or 0),
                "filters": filter_payload,
            },
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug(_AUDIT_ROUTER_FALLBACK_LOG_MESSAGE, exc)

    return AuditLogPurgeResponse(
        dry_run=bool(dry_run),
        scope=str(purge_scope),
        retention_days=int(retention_days or 0),
        cutoff=cutoff,
        max_delete=int(max_delete or 0),
        eligible=int(eligible or 0),
        deleted=int(deleted or 0),
        filters=filter_payload,
    )


@router.delete("/logs/{log_id}", response_model=AuditLogDeleteResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def delete_audit_log(
    log_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Delete one audit log row for the current tenant."""
    return _delete_audit_logs_by_id(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        ids=[log_id],
        action="audit.logs.delete",
    )


@router.post("/logs/bulk-delete", response_model=AuditLogDeleteResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def bulk_delete_audit_logs(
    payload: AuditLogDeleteRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Delete selected audit log rows for the current tenant."""
    return _delete_audit_logs_by_id(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        ids=payload.ids,
        action="audit.logs.bulk_delete",
    )


def _delete_audit_logs_by_id(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    ids: list[UUID],
    action: str,
) -> AuditLogDeleteResponse:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.AUDIT_MANAGE,
        detail="No permission to manage audit logs",
    )

    unique_ids = _dedupe_uuids(ids)
    deleted = int(delete_audit_log_rows(db, tenant_id=tenant_id, ids=unique_ids, commit=True) or 0)
    missing = max(0, len(unique_ids) - deleted)

    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action=action,
            resource_type="audit_logs",
            resource_id=str(unique_ids[0]) if len(unique_ids) == 1 else None,
            details={
                "requested": len(unique_ids),
                "deleted": deleted,
                "missing": missing,
                "ids": [str(value) for value in unique_ids[:50]],
            },
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug("Ignoring non-critical audit delete fallback failure: %s", exc)

    return AuditLogDeleteResponse(
        requested=len(unique_ids),
        deleted=deleted,
        missing=missing,
        ids=unique_ids,
    )


_ACCESS_GRAPH_RECORD_SCHEMA = "mimirq.access_graph_export_record.v1"
_ACCESS_GRAPH_PAGE_SCHEMA = "mimirq.access_graph_export_page.v1"
_ACCESS_GRAPH_KINDS = [
    "group",
    "group_member",
    "dataset",
    "dataset_member_permission",
    "dataset_group_permission",
    "document",
    "document_member_permission",
    "document_group_permission",
]


def _hash16(raw: object) -> str | None:
    s = str(raw or "").strip()
    if not s:
        return None
    return stable_hash(s, length=16)


def _apply_created_cursor(q, model, *, after_created_at: datetime | None, after_id: UUID | None):  # noqa: ANN001
    if after_created_at is None:
        return q
    if after_id is not None:
        return q.filter(
            or_(
                model.created_at > after_created_at,
                and_(model.created_at == after_created_at, model.id > after_id),
            )
        )
    return q.filter(model.created_at > after_created_at)


def _export_access_graph_row(*, kind: str, row: Any, include_sensitive: bool) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema": _ACCESS_GRAPH_RECORD_SCHEMA,
        "kind": kind,
        "id": str(getattr(row, "id", "") or ""),
        "tenant_id": str(getattr(row, "tenant_id", "") or ""),
        "created_at": _dt_to_json(getattr(row, "created_at", None)),
    }

    if kind == "group":
        name = str(getattr(row, "name", "") or "")
        external_id = str(getattr(row, "external_id", "") or "")
        base.update(
            {
                "name": (name or None) if include_sensitive else None,
                "name_hash": _hash16(name) if name else None,
                "external_id": (external_id or None) if include_sensitive else None,
                "external_id_hash": _hash16(external_id) if external_id else None,
                "updated_at": _dt_to_json(getattr(row, "updated_at", None)),
            }
        )
        return base

    if kind == "group_member":
        user_id = str(getattr(row, "user_id", "") or "")
        base.update(
            {
                "group_id": str(getattr(row, "group_id", "") or ""),
                "user_id": (user_id or None) if include_sensitive else None,
                "user_id_hash": _hash16(user_id) if user_id else None,
            }
        )
        return base

    if kind == "dataset":
        name = str(getattr(row, "name", "") or "")
        owner_id = str(getattr(row, "owner_id", "") or "")
        perm = getattr(row, "permission", None)
        perm_value = getattr(perm, "value", None) or str(perm or "")
        base.update(
            {
                "name": (name or None) if include_sensitive else None,
                "name_hash": _hash16(name) if name else None,
                "permission": str(perm_value or ""),
                "owner_id": (owner_id or None) if include_sensitive else None,
                "owner_id_hash": _hash16(owner_id) if owner_id else None,
                "updated_at": _dt_to_json(getattr(row, "updated_at", None)),
            }
        )
        return base

    if kind == "dataset_member_permission":
        account_id = str(getattr(row, "account_id", "") or "")
        base.update(
            {
                "dataset_id": str(getattr(row, "dataset_id", "") or ""),
                "account_id": (account_id or None) if include_sensitive else None,
                "account_id_hash": _hash16(account_id) if account_id else None,
            }
        )
        return base

    if kind == "dataset_group_permission":
        base.update(
            {
                "dataset_id": str(getattr(row, "dataset_id", "") or ""),
                "group_id": str(getattr(row, "group_id", "") or ""),
            }
        )
        return base

    if kind == "document":
        owner_id = str(getattr(row, "owner_id", "") or "")
        access_mode = str(getattr(row, "access_mode", "") or "").strip() or None
        dataset_id = getattr(row, "dataset_id", None)
        base.update(
            {
                "dataset_id": (str(dataset_id) if dataset_id is not None else None),
                "access_mode": access_mode,
                "owner_id": (owner_id or None) if include_sensitive else None,
                "owner_id_hash": _hash16(owner_id) if owner_id else None,
                "updated_at": _dt_to_json(getattr(row, "updated_at", None)),
            }
        )
        return base

    if kind == "document_member_permission":
        account_id = str(getattr(row, "account_id", "") or "")
        base.update(
            {
                "document_id": str(getattr(row, "document_id", "") or ""),
                "account_id": (account_id or None) if include_sensitive else None,
                "account_id_hash": _hash16(account_id) if account_id else None,
            }
        )
        return base

    if kind == "document_group_permission":
        base.update(
            {
                "document_id": str(getattr(row, "document_id", "") or ""),
                "group_id": str(getattr(row, "group_id", "") or ""),
            }
        )
        return base

    base["kind"] = "unknown"
    return base


@router.get("/access-graph/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_access_graph_ndjson(
    limit: Annotated[int, Query(ge=1, le=10000)] = 1000,
    after_kind: Annotated[str | None, Query(max_length=64, description='Cursor: last seen kind')] = None,
    after_created_at: Annotated[datetime | None, Query(description='Cursor: last seen created_at')] = None,
    after_id: Annotated[UUID | None, Query(description='Cursor: last seen id (tie-breaker)')] = None,
    include_sensitive: Annotated[bool, Query(description='Include raw user/group/dataset identifiers (admin/auditor only)')] = False,
    export_format: Annotated[str, Query(description='ndjson|json')] = "ndjson",
    gzip: Annotated[bool, Query(description='Return gzip-compressed NDJSON/JSON (Content-Encoding: gzip)')] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Export an access graph page (groups + memberships + allowlists) as NDJSON or JSON.

    Stable paging:
    - The export is deterministic across kinds and ordered by (created_at, id) within each kind.
    - Cursor uses (after_kind, after_created_at, after_id).

    Security posture:
    - Requires audit.read (owner/admin/auditor).
    - PII-safe by default (include_sensitive=false): raw user ids are omitted; only hashes are exported.
    - Never exports document content/filenames/paths.
    """
    _ensure_admin(db, tenant_id, account_id)

    fmt = str(export_format or "ndjson").strip().lower() or "ndjson"
    if fmt not in {"ndjson", "json"}:
        raise HTTPException(status_code=400, detail="export_format must be one of: ndjson, json")

    k = str(after_kind or "").strip().lower() or None
    if (after_created_at is not None or after_id is not None) and not k:
        raise HTTPException(status_code=400, detail="after_kind is required when using after_created_at/after_id")
    if k is not None and k not in _ACCESS_GRAPH_KINDS:
        raise HTTPException(status_code=400, detail=f"after_kind must be one of: {', '.join(_ACCESS_GRAPH_KINDS)}")

    start_idx = _ACCESS_GRAPH_KINDS.index(k) if k else 0
    max_items = int(limit or 0)

    out: list[dict[str, Any]] = []

    def _query_rows(kind: str, *, after_dt: datetime | None, after_row_id: UUID | None, take: int):  # noqa: ANN001
        if kind == "group":
            q = db.query(TenantGroup).filter(TenantGroup.tenant_id == tenant_id)
            q = _apply_created_cursor(q, TenantGroup, after_created_at=after_dt, after_id=after_row_id)
            return q.order_by(TenantGroup.created_at.asc(), TenantGroup.id.asc()).limit(take).all()
        if kind == "group_member":
            q = db.query(TenantGroupMember).filter(TenantGroupMember.tenant_id == tenant_id)
            q = _apply_created_cursor(q, TenantGroupMember, after_created_at=after_dt, after_id=after_row_id)
            return q.order_by(TenantGroupMember.created_at.asc(), TenantGroupMember.id.asc()).limit(take).all()
        if kind == "dataset":
            q = db.query(Dataset).filter(Dataset.tenant_id == tenant_id)
            q = _apply_created_cursor(q, Dataset, after_created_at=after_dt, after_id=after_row_id)
            return q.order_by(Dataset.created_at.asc(), Dataset.id.asc()).limit(take).all()
        if kind == "dataset_member_permission":
            q = db.query(DatasetPermission).filter(DatasetPermission.tenant_id == tenant_id)
            q = _apply_created_cursor(q, DatasetPermission, after_created_at=after_dt, after_id=after_row_id)
            return q.order_by(DatasetPermission.created_at.asc(), DatasetPermission.id.asc()).limit(take).all()
        if kind == "dataset_group_permission":
            q = db.query(DatasetGroupPermission).filter(DatasetGroupPermission.tenant_id == tenant_id)
            q = _apply_created_cursor(q, DatasetGroupPermission, after_created_at=after_dt, after_id=after_row_id)
            return (
                q.order_by(DatasetGroupPermission.created_at.asc(), DatasetGroupPermission.id.asc()).limit(take).all()
            )
        if kind == "document":
            q = db.query(Document).filter(Document.tenant_id == tenant_id)
            q = _apply_created_cursor(q, Document, after_created_at=after_dt, after_id=after_row_id)
            return q.order_by(Document.created_at.asc(), Document.id.asc()).limit(take).all()
        if kind == "document_member_permission":
            q = db.query(DocumentPermission).filter(DocumentPermission.tenant_id == tenant_id)
            q = _apply_created_cursor(q, DocumentPermission, after_created_at=after_dt, after_id=after_row_id)
            return q.order_by(DocumentPermission.created_at.asc(), DocumentPermission.id.asc()).limit(take).all()
        if kind == "document_group_permission":
            q = db.query(DocumentGroupPermission).filter(DocumentGroupPermission.tenant_id == tenant_id)
            q = _apply_created_cursor(q, DocumentGroupPermission, after_created_at=after_dt, after_id=after_row_id)
            return (
                q.order_by(DocumentGroupPermission.created_at.asc(), DocumentGroupPermission.id.asc()).limit(take).all()
            )
        return []

    for kind in _ACCESS_GRAPH_KINDS[start_idx:]:
        remaining = max_items - len(out)
        if remaining <= 0:
            break
        rows = _query_rows(
            kind,
            after_dt=(after_created_at if kind == k else None),
            after_row_id=(after_id if kind == k else None),
            take=remaining,
        )
        for row in rows:
            out.append(_export_access_graph_row(kind=kind, row=row, include_sensitive=bool(include_sensitive)))
            if len(out) >= max_items:
                break
        if len(out) >= max_items:
            break

        # Kind exhausted: keep filling from the next kind in the same page.
        if len(rows) >= remaining:
            break

    has_more = bool(len(out) >= max_items and out)
    next_cursor = None
    if has_more:
        last = out[-1]
        next_cursor = {
            "after_kind": str(last.get("kind") or ""),
            "after_created_at": last.get("created_at"),
            "after_id": last.get("id"),
        }

    # Best-effort audit log (PII-safe).
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="compliance.access_graph.export",
            resource_type="tenant",
            resource_id=str(tenant_id),
            details={
                "limit": int(limit or 0),
                "returned": int(len(out)),
                "after_kind": k,
                "after_created_at": (after_created_at.isoformat() if after_created_at else None),
                "after_id": (str(after_id) if after_id else None),
                "include_sensitive": bool(include_sensitive),
                "export_format": fmt,
                "gzip": bool(gzip),
            },
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug(_AUDIT_ROUTER_FALLBACK_LOG_MESSAGE, exc)

    headers: dict[str, str] = {
        "Cache-Control": "no-store",
    }
    if next_cursor:
        headers["X-Next-Cursor"] = json.dumps(next_cursor, ensure_ascii=True, separators=(",", ":"))

    if fmt == "json":
        payload = {
            "schema": _ACCESS_GRAPH_PAGE_SCHEMA,
            "limit": int(limit or 0),
            "returned": int(len(out)),
            "next_cursor": next_cursor,
            "items": out,
        }
        content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
        if gzip:
            headers["Content-Encoding"] = "gzip"
            content = gzip_lib.compress(content)
        return Response(content=content, media_type="application/json", headers=headers)

    def _iter_lines() -> Iterator[bytes]:
        for item in out:
            line = json.dumps(item, ensure_ascii=False, separators=(",", ":"), default=str) + "\n"
            yield line.encode("utf-8")

    body_iter: Iterator[bytes] = _iter_lines()
    if gzip:
        headers["Content-Encoding"] = "gzip"
        body_iter = _iter_gzip_chunks(body_iter)

    return StreamingResponse(body_iter, media_type="application/x-ndjson", headers=headers)


@router.get("/access-graph/summary", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def access_graph_summary(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    PII-minimal access review summary for a tenant (bounded JSON).

    Intended for:
    - Security audits / access reviews
    - Troubleshooting "why is this user denied" (at the directory/config level)
    """
    _ensure_admin(db, tenant_id, account_id)

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

    dataset_member_allowlist_count = int(
        db.query(DatasetPermission).filter(DatasetPermission.tenant_id == tenant_id).count()
    )
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

    payload = {
        "schema": "mimirq.access_graph_summary.v1",
        "tenant_id": str(tenant_id),
        "generated_at": datetime.now(UTC).isoformat(),
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
    }

    # Best-effort audit log (PII-safe).
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="compliance.access_graph.summary",
            resource_type="tenant",
            resource_id=str(tenant_id),
            details={
                "group_count": int(group_count),
                "group_member_count": int(group_member_count),
                "dataset_count": int(dataset_count),
                "document_count": int(document_count),
            },
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug(_AUDIT_ROUTER_FALLBACK_LOG_MESSAGE, exc)

    return payload
