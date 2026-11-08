"""
Audit log endpoints (admin-only).

This is intentionally minimal and PII-safe by default.
"""

import gzip as gzip_lib
import io
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, desc, or_
from sqlalchemy.orm import Query as ORMQuery
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.audit import (
    AuditLogDeleteRequest,
    AuditLogDeleteResponse,
    AuditLogExportParams,
    AuditLogFilterParams,
    AuditLogListResponse,
    AuditLogOut,
    AuditLogPurgeParams,
    AuditLogPurgeResponse,
)
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
from app.services.audit_log_service import apply_audit_log_filters, audit_log_event
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


def audit_log_filter_params(
    actor_id: Annotated[str | None, Query(max_length=255)] = None,
    action: Annotated[str | None, Query(max_length=128)] = None,
    resource_type: Annotated[str | None, Query(max_length=64)] = None,
    resource_id: Annotated[str | None, Query(max_length=255)] = None,
    request_id: Annotated[str | None, Query(max_length=128)] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> AuditLogFilterParams:
    return AuditLogFilterParams(
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        since=since,
        until=until,
    )


def audit_log_export_params(
    limit: Annotated[int, Query(ge=1, le=10000)] = 1000,
    after_created_at: Annotated[datetime | None, Query(description="Cursor: last seen created_at")] = None,
    after_id: Annotated[UUID | None, Query(description="Cursor: last seen id (tie-breaker)")] = None,
    include_sensitive: Annotated[bool, Query(description="Include sensitive detail keys (admin/auditor only)")] = False,
    gzip: Annotated[bool, Query(description="Return gzip-compressed NDJSON (Content-Encoding: gzip)")] = False,
) -> AuditLogExportParams:
    return AuditLogExportParams(
        limit=limit,
        after_created_at=after_created_at,
        after_id=after_id,
        include_sensitive=include_sensitive,
        gzip=gzip,
    )


def audit_log_purge_params(
    retention_days: Annotated[int, Query(ge=1, le=3650, description="Delete logs older than N days")] = 90,
    max_delete: Annotated[int, Query(ge=1, le=1000000, description="Max rows to delete in this call")] = 100_000,
    dry_run: Annotated[bool, Query(description="Plan only; do not delete rows")] = True,
    purge_scope: Annotated[
        Literal["retention", "filtered"],
        Query(description="retention=older than N days; filtered=current explicit filters"),
    ] = "retention",
) -> AuditLogPurgeParams:
    return AuditLogPurgeParams(
        retention_days=retention_days,
        max_delete=max_delete,
        dry_run=dry_run,
        purge_scope=purge_scope,
    )


def _sanitize_details(details: dict[str, Any], *, include_sensitive: bool) -> dict[str, Any]:
    if include_sensitive:
        return dict(details)
    out: dict[str, Any] = {}
    for key, value in details.items():
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
            if buffer.tell() >= flush_bytes:
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


def _build_audit_log_query(db: Session, *, tenant_id: UUID, filters: AuditLogFilterParams) -> ORMQuery[AuditLog]:
    return apply_audit_log_filters(
        db.query(AuditLog).filter(AuditLog.tenant_id == tenant_id),
        **filters.model_dump(),
    )


def _apply_audit_log_export_cursor(q: ORMQuery[AuditLog], export: AuditLogExportParams) -> ORMQuery[AuditLog]:
    if export.after_created_at is None:
        return q
    if export.after_id is not None:
        return q.filter(
            or_(
                AuditLog.created_at > export.after_created_at,
                and_(AuditLog.created_at == export.after_created_at, AuditLog.id > export.after_id),
            )
        )
    return q.filter(AuditLog.created_at > export.after_created_at)


def _iter_audit_log_export_lines(
    rows: list[AuditLog],
    *,
    include_sensitive: bool,
) -> Iterator[bytes]:
    for row in rows:
        obj = AuditLogOut.model_validate(row)
        obj.details = _sanitize_details(obj.details, include_sensitive=include_sensitive)
        payload = obj.model_dump(mode="json")
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        yield line.encode("utf-8")


def _build_ndjson_streaming_response(
    body_iter: Iterator[bytes],
    *,
    gzip_enabled: bool,
    headers: dict[str, str] | None = None,
) -> StreamingResponse:
    response_headers = dict(headers or {})
    if gzip_enabled:
        response_headers["Content-Encoding"] = "gzip"
        body_iter = _iter_gzip_chunks(body_iter)
    return StreamingResponse(
        body_iter,
        media_type="application/x-ndjson",
        headers=response_headers,
    )


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
) -> dict[str, Any]:
    _ensure_admin(db, tenant_id, account_id)

    q = _build_audit_log_query(
        db,
        tenant_id=tenant_id,
        filters=AuditLogFilterParams(
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id,
            since=since,
            until=until,
        ),
    )

    total = q.count()
    items = q.order_by(desc(AuditLog.created_at), desc(AuditLog.id)).offset(skip).limit(limit).all()
    payload: list[AuditLogOut] = []
    for item in items:
        obj = AuditLogOut.model_validate(item)
        obj.details = _sanitize_details(obj.details, include_sensitive=include_sensitive)
        payload.append(obj)
    return {"total": total, "items": payload}


@router.get("/logs/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_audit_logs(
    filters: Annotated[AuditLogFilterParams, Depends(audit_log_filter_params)],
    export: Annotated[AuditLogExportParams, Depends(audit_log_export_params)],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> StreamingResponse:
    """
    Export audit logs as NDJSON (JSON Lines) for SIEM ingestion.

    Notes:
    - Ordered ascending by (created_at, id) to support incremental exports.
    - Uses cursor params (after_created_at, after_id) for efficient resume.
    - Details are sanitized by default (include_sensitive=false).
    """
    _ensure_admin(db, tenant_id, account_id)

    q = _build_audit_log_query(db, tenant_id=tenant_id, filters=filters)
    q = _apply_audit_log_export_cursor(q, export)
    rows = q.order_by(AuditLog.created_at.asc(), AuditLog.id.asc()).limit(export.limit).all()
    return _build_ndjson_streaming_response(
        _iter_audit_log_export_lines(rows, include_sensitive=export.include_sensitive),
        gzip_enabled=export.gzip,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/logs/purge", response_model=AuditLogPurgeResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def purge_audit_logs(
    params: Annotated[AuditLogPurgeParams, Depends(audit_log_purge_params)],
    filters: Annotated[AuditLogFilterParams, Depends(audit_log_filter_params)],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> AuditLogPurgeResponse:
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
    cutoff = now - timedelta(days=params.retention_days)

    filter_payload: dict[str, Any] = {
        k: v
        for k, v in {
            "actor_id": filters.actor_id,
            "action": filters.action,
            "resource_type": filters.resource_type,
            "resource_id": filters.resource_id,
            "request_id": filters.request_id,
            "since": filters.since.isoformat() if filters.since is not None else None,
            "until": filters.until.isoformat() if filters.until is not None else None,
        }.items()
        if v not in (None, "")
    }

    if params.purge_scope == "filtered" and not filter_payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one filter is required for filtered audit log purge",
        )

    if params.purge_scope == "filtered":
        eligible = plan_filtered_audit_log_purge(
            db,
            tenant_id=tenant_id,
            max_delete=params.max_delete,
            **filters.model_dump(),
        )
    else:
        eligible = plan_audit_log_purge(db, tenant_id=tenant_id, cutoff=cutoff, max_delete=params.max_delete)

    deleted = 0
    if not params.dry_run:
        if params.purge_scope == "filtered":
            deleted = purge_filtered_audit_log_rows(
                db,
                tenant_id=tenant_id,
                max_delete=params.max_delete,
                commit=True,
                **filters.model_dump(),
            )
        else:
            deleted = purge_audit_log_rows(
                db,
                tenant_id=tenant_id,
                cutoff=cutoff,
                max_delete=params.max_delete,
                commit=True,
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
                "dry_run": params.dry_run,
                "purge_scope": params.purge_scope,
                "retention_days": params.retention_days,
                "cutoff": cutoff.isoformat(),
                "max_delete": params.max_delete,
                "eligible": eligible,
                "deleted": deleted,
                "filters": filter_payload,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Audit purge completed but its audit record failed", exc_info=True)

    return AuditLogPurgeResponse(
        dry_run=params.dry_run,
        scope=params.purge_scope,
        retention_days=params.retention_days,
        cutoff=cutoff,
        max_delete=params.max_delete,
        eligible=eligible,
        deleted=deleted,
        filters=filter_payload,
    )


@router.delete("/logs/{log_id}", response_model=AuditLogDeleteResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def delete_audit_log(
    log_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> AuditLogDeleteResponse:
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
) -> AuditLogDeleteResponse:
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

    unique_ids = list(dict.fromkeys(ids))
    deleted = delete_audit_log_rows(db, tenant_id=tenant_id, ids=unique_ids, commit=True)
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
        db.rollback()
        logger.warning("Audit deletion completed but its audit record failed", exc_info=True)

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


def _hash16(raw: str) -> str | None:
    s = raw.strip()
    if not s:
        return None
    return stable_hash(s, length=16)


def _apply_created_cursor(
    q: ORMQuery, model: Any, *, after_created_at: datetime | None, after_id: UUID | None
) -> ORMQuery:
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
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "created_at": _dt_to_json(row.created_at),
    }

    if kind == "group":
        name = row.name
        external_id = row.external_id
        base.update(
            {
                "name": name if include_sensitive else None,
                "name_hash": _hash16(name) if name else None,
                "external_id": external_id if include_sensitive else None,
                "external_id_hash": _hash16(external_id) if external_id else None,
                "updated_at": _dt_to_json(row.updated_at),
            }
        )
        return base

    if kind == "group_member":
        user_id = row.user_id
        base.update(
            {
                "group_id": str(row.group_id),
                "user_id": user_id if include_sensitive else None,
                "user_id_hash": _hash16(user_id) if user_id else None,
            }
        )
        return base

    if kind == "dataset":
        name = row.name
        owner_id = row.owner_id
        base.update(
            {
                "name": name if include_sensitive else None,
                "name_hash": _hash16(name) if name else None,
                "permission": row.permission.value,
                "owner_id": owner_id if include_sensitive else None,
                "owner_id_hash": _hash16(owner_id) if owner_id else None,
                "updated_at": _dt_to_json(row.updated_at),
            }
        )
        return base

    if kind == "dataset_member_permission":
        account_id = row.account_id
        base.update(
            {
                "dataset_id": str(row.dataset_id),
                "account_id": account_id if include_sensitive else None,
                "account_id_hash": _hash16(account_id) if account_id else None,
            }
        )
        return base

    if kind == "dataset_group_permission":
        base.update(
            {
                "dataset_id": str(row.dataset_id),
                "group_id": str(row.group_id),
            }
        )
        return base

    if kind == "document":
        owner_id = row.owner_id
        access_mode = row.access_mode
        dataset_id = row.dataset_id
        base.update(
            {
                "dataset_id": (str(dataset_id) if dataset_id is not None else None),
                "access_mode": access_mode,
                "owner_id": owner_id if include_sensitive else None,
                "owner_id_hash": _hash16(owner_id) if owner_id else None,
                "updated_at": _dt_to_json(row.updated_at),
            }
        )
        return base

    if kind == "document_member_permission":
        account_id = row.account_id
        base.update(
            {
                "document_id": str(row.document_id),
                "account_id": account_id if include_sensitive else None,
                "account_id_hash": _hash16(account_id) if account_id else None,
            }
        )
        return base

    if kind == "document_group_permission":
        base.update(
            {
                "document_id": str(row.document_id),
                "group_id": str(row.group_id),
            }
        )
        return base

    base["kind"] = "unknown"
    return base


_ACCESS_GRAPH_MODELS = {
    "group": TenantGroup,
    "group_member": TenantGroupMember,
    "dataset": Dataset,
    "dataset_member_permission": DatasetPermission,
    "dataset_group_permission": DatasetGroupPermission,
    "document": Document,
    "document_member_permission": DocumentPermission,
    "document_group_permission": DocumentGroupPermission,
}


def _normalize_access_graph_export_params(
    *,
    export_format: str,
    after_kind: str | None,
    after_created_at: datetime | None,
    after_id: UUID | None,
) -> tuple[str, str | None]:
    fmt = export_format.strip().lower() or "ndjson"
    if fmt not in {"ndjson", "json"}:
        raise HTTPException(status_code=400, detail="export_format must be one of: ndjson, json")

    kind = (after_kind or "").strip().lower() or None
    if (after_created_at is not None or after_id is not None) and not kind:
        raise HTTPException(status_code=400, detail="after_kind is required when using after_created_at/after_id")
    if kind is not None and kind not in _ACCESS_GRAPH_KINDS:
        raise HTTPException(status_code=400, detail=f"after_kind must be one of: {', '.join(_ACCESS_GRAPH_KINDS)}")
    return fmt, kind


def _query_access_graph_rows(
    db: Session,
    *,
    tenant_id: UUID,
    kind: str,
    after_dt: datetime | None,
    after_row_id: UUID | None,
    take: int,
) -> list[Any]:
    model = _ACCESS_GRAPH_MODELS[kind]
    q = db.query(model).filter(model.tenant_id == tenant_id)
    q = _apply_created_cursor(q, model, after_created_at=after_dt, after_id=after_row_id)
    return q.order_by(model.created_at.asc(), model.id.asc()).limit(take).all()


def _collect_access_graph_page(
    db: Session,
    *,
    tenant_id: UUID,
    include_sensitive: bool,
    limit: int,
    after_kind: str | None,
    after_created_at: datetime | None,
    after_id: UUID | None,
) -> list[dict[str, Any]]:
    start_idx = _ACCESS_GRAPH_KINDS.index(after_kind) if after_kind else 0
    out: list[dict[str, Any]] = []
    max_items = limit
    for kind in _ACCESS_GRAPH_KINDS[start_idx:]:
        remaining = max_items - len(out)
        if remaining <= 0:
            break
        rows = _query_access_graph_rows(
            db,
            tenant_id=tenant_id,
            kind=kind,
            after_dt=(after_created_at if kind == after_kind else None),
            after_row_id=(after_id if kind == after_kind else None),
            take=remaining,
        )
        out.extend(_export_access_graph_row(kind=kind, row=row, include_sensitive=include_sensitive) for row in rows)
        if len(out) >= max_items or len(rows) >= remaining:
            break
    return out[:max_items]


def _access_graph_next_cursor(out: list[dict[str, Any]], *, limit: int) -> dict[str, Any] | None:
    if len(out) < limit or not out:
        return None
    last = out[-1]
    return {
        "after_kind": last["kind"],
        "after_created_at": last["created_at"],
        "after_id": last["id"],
    }


def _audit_access_graph_export(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    limit: int,
    returned: int,
    after_kind: str | None,
    after_created_at: datetime | None,
    after_id: UUID | None,
    include_sensitive: bool,
    export_format: str,
    gzip_enabled: bool,
) -> None:
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="compliance.access_graph.export",
            resource_type="tenant",
            resource_id=str(tenant_id),
            details={
                "limit": limit,
                "returned": returned,
                "after_kind": after_kind,
                "after_created_at": (after_created_at.isoformat() if after_created_at else None),
                "after_id": (str(after_id) if after_id else None),
                "include_sensitive": include_sensitive,
                "export_format": export_format,
                "gzip": gzip_enabled,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Access graph export audit failed", exc_info=True)


def _build_access_graph_headers(next_cursor: dict[str, Any] | None) -> dict[str, str]:
    headers: dict[str, str] = {"Cache-Control": "no-store"}
    if next_cursor:
        headers["X-Next-Cursor"] = json.dumps(next_cursor, ensure_ascii=True, separators=(",", ":"))
    return headers


def _access_graph_json_response(
    *,
    limit: int,
    out: list[dict[str, Any]],
    next_cursor: dict[str, Any] | None,
    headers: dict[str, str],
    gzip_enabled: bool,
) -> Response:
    payload = {
        "schema": _ACCESS_GRAPH_PAGE_SCHEMA,
        "limit": limit,
        "returned": len(out),
        "next_cursor": next_cursor,
        "items": out,
    }
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    response_headers = dict(headers)
    if gzip_enabled:
        response_headers["Content-Encoding"] = "gzip"
        content = gzip_lib.compress(content)
    return Response(content=content, media_type="application/json", headers=response_headers)


@router.get("/access-graph/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_access_graph_ndjson(
    limit: Annotated[int, Query(ge=1, le=10000)] = 1000,
    after_kind: Annotated[str | None, Query(max_length=64, description="Cursor: last seen kind")] = None,
    after_created_at: Annotated[datetime | None, Query(description="Cursor: last seen created_at")] = None,
    after_id: Annotated[UUID | None, Query(description="Cursor: last seen id (tie-breaker)")] = None,
    include_sensitive: Annotated[
        bool, Query(description="Include raw user/group/dataset identifiers (admin/auditor only)")
    ] = False,
    export_format: Annotated[str, Query(description="ndjson|json")] = "ndjson",
    gzip: Annotated[bool, Query(description="Return gzip-compressed NDJSON/JSON (Content-Encoding: gzip)")] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
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

    fmt, kind = _normalize_access_graph_export_params(
        export_format=export_format,
        after_kind=after_kind,
        after_created_at=after_created_at,
        after_id=after_id,
    )
    out = _collect_access_graph_page(
        db,
        tenant_id=tenant_id,
        include_sensitive=include_sensitive,
        limit=limit,
        after_kind=kind,
        after_created_at=after_created_at,
        after_id=after_id,
    )
    next_cursor = _access_graph_next_cursor(out, limit=limit)
    _audit_access_graph_export(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        limit=limit,
        returned=len(out),
        after_kind=kind,
        after_created_at=after_created_at,
        after_id=after_id,
        include_sensitive=include_sensitive,
        export_format=fmt,
        gzip_enabled=gzip,
    )
    headers = _build_access_graph_headers(next_cursor)
    if fmt == "json":
        return _access_graph_json_response(
            limit=limit,
            out=out,
            next_cursor=next_cursor,
            headers=headers,
            gzip_enabled=gzip,
        )
    return _build_ndjson_streaming_response(
        (
            (json.dumps(item, ensure_ascii=False, separators=(",", ":"), default=str) + "\n").encode("utf-8")
            for item in out
        ),
        gzip_enabled=gzip,
        headers=headers,
    )


@router.get("/access-graph/summary", response_model=None, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def access_graph_summary(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """
    PII-minimal access review summary for a tenant (bounded JSON).

    Intended for:
    - Security audits / access reviews
    - Troubleshooting "why is this user denied" (at the directory/config level)
    """
    _ensure_admin(db, tenant_id, account_id)

    group_count = db.query(TenantGroup).filter(TenantGroup.tenant_id == tenant_id).count()
    group_member_count = db.query(TenantGroupMember).filter(TenantGroupMember.tenant_id == tenant_id).count()

    dataset_count = db.query(Dataset).filter(Dataset.tenant_id == tenant_id).count()
    dataset_permission_counts = {
        "all_team_members": (
            db.query(Dataset)
            .filter(Dataset.tenant_id == tenant_id, Dataset.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS)
            .count()
        ),
        "only_me": (
            db.query(Dataset)
            .filter(Dataset.tenant_id == tenant_id, Dataset.permission == DatasetPermissionEnum.ONLY_ME)
            .count()
        ),
        "partial_members": (
            db.query(Dataset)
            .filter(Dataset.tenant_id == tenant_id, Dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS)
            .count()
        ),
    }

    dataset_member_allowlist_count = (
        db.query(DatasetPermission).filter(DatasetPermission.tenant_id == tenant_id).count()
    )
    dataset_group_allowlist_count = (
        db.query(DatasetGroupPermission).filter(DatasetGroupPermission.tenant_id == tenant_id).count()
    )

    document_count = db.query(Document).filter(Document.tenant_id == tenant_id).count()

    doc_inherit_count = (
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
    doc_partial_count = (
        db.query(Document).filter(Document.tenant_id == tenant_id, Document.access_mode == "partial_members").count()
    )
    doc_only_me_count = (
        db.query(Document).filter(Document.tenant_id == tenant_id, Document.access_mode == "only_me").count()
    )
    doc_all_team_count = (
        db.query(Document).filter(Document.tenant_id == tenant_id, Document.access_mode == "all_team_members").count()
    )
    doc_known = doc_inherit_count + doc_partial_count + doc_only_me_count + doc_all_team_count
    doc_unknown_count = max(0, document_count - doc_known)

    document_access_mode_counts = {
        "inherit": doc_inherit_count,
        "partial_members": doc_partial_count,
        "only_me": doc_only_me_count,
        "all_team_members": doc_all_team_count,
        "unknown": doc_unknown_count,
    }

    document_member_allowlist_count = (
        db.query(DocumentPermission).filter(DocumentPermission.tenant_id == tenant_id).count()
    )
    document_group_allowlist_count = (
        db.query(DocumentGroupPermission).filter(DocumentGroupPermission.tenant_id == tenant_id).count()
    )

    payload = {
        "schema": "mimirq.access_graph_summary.v1",
        "tenant_id": str(tenant_id),
        "generated_at": datetime.now(UTC).isoformat(),
        "group_count": group_count,
        "group_member_count": group_member_count,
        "dataset_count": dataset_count,
        "dataset_permission_counts": dataset_permission_counts,
        "dataset_member_allowlist_count": dataset_member_allowlist_count,
        "dataset_group_allowlist_count": dataset_group_allowlist_count,
        "document_count": document_count,
        "document_access_mode_counts": document_access_mode_counts,
        "document_member_allowlist_count": document_member_allowlist_count,
        "document_group_allowlist_count": document_group_allowlist_count,
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
                "group_count": group_count,
                "group_member_count": group_member_count,
                "dataset_count": dataset_count,
                "document_count": document_count,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Access graph summary audit failed", exc_info=True)

    return payload
