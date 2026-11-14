"""
Audit log endpoints (admin-only).

This is intentionally minimal and PII-safe by default.
"""

import gzip as gzip_lib
import io
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, desc, or_
from sqlalchemy.orm import Query as ORMQuery
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.system import (
    AuditLogDeleteRequest,
    AuditLogDeleteResponse,
    AuditLogExportParams,
    AuditLogFilterParams,
    AuditLogListResponse,
    AuditLogOut,
    AuditLogPurgeParams,
    AuditLogPurgeResponse,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES
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

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger(__name__)

_SENSITIVE_DETAIL_KEYS = frozenset(
    {
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
)


def _ensure_audit_read_permission(db: Session, tenant_id: UUID, account_id: str) -> None:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.AUDIT_READ,
        detail="No permission to access audit logs",
    )


def _record_audit_operation(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    action: str,
    resource_type: str,
    resource_id: str | None,
    details: dict[str, Any],
    failure_message: str,
) -> None:
    """Commit the operation's audit sidecar without hiding a primary-operation failure."""
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning(failure_message, exc_info=True)


def _sanitize_details(details: dict[str, Any], *, include_sensitive: bool) -> dict[str, Any]:
    if include_sensitive:
        return dict(details)
    out: dict[str, Any] = {}
    for key, value in details.items():
        lowered = key.strip().lower()
        if lowered in _SENSITIVE_DETAIL_KEYS:
            continue
        if isinstance(value, dict):
            out[key] = _sanitize_details(value, include_sensitive=False)
        else:
            out[key] = value
    return out


def _iter_gzip_chunks(chunks: Iterator[bytes], *, flush_bytes: int = 64 * 1024) -> Iterator[bytes]:
    """Compress export chunks; close gzip on failure or early iterator exit."""
    buffer = io.BytesIO()
    with gzip_lib.GzipFile(fileobj=buffer, mode="wb") as compressor:
        for chunk in chunks:
            compressor.write(chunk)
            if buffer.tell() >= flush_bytes:
                compressor.flush()
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)
    yield buffer.getvalue()


def _dt_to_json(value: datetime | None) -> str | None:
    """Keep UTC cursors URL-friendly while preserving naive timestamps and other offsets."""
    if value is None:
        return None
    serialized = value.isoformat()
    return serialized[:-6] + "Z" if serialized.endswith("+00:00") else serialized


def _build_audit_log_query(db: Session, *, tenant_id: UUID, filters: AuditLogFilterParams) -> ORMQuery[AuditLog]:
    return apply_audit_log_filters(
        db.query(AuditLog).filter(AuditLog.tenant_id == tenant_id),
        **filters.model_dump(include=set(AuditLogFilterParams.model_fields)),
    )


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
    headers: dict[str, str],
) -> StreamingResponse:
    response_headers = dict(headers)
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
    _ensure_audit_read_permission(db, tenant_id, account_id)

    query = _build_audit_log_query(
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

    total = query.count()
    items = query.order_by(desc(AuditLog.created_at), desc(AuditLog.id)).offset(skip).limit(limit).all()
    payload: list[AuditLogOut] = []
    for item in items:
        obj = AuditLogOut.model_validate(item)
        obj.details = _sanitize_details(obj.details, include_sensitive=include_sensitive)
        payload.append(obj)
    return {"total": total, "items": payload}


@router.get("/logs/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_audit_logs(
    export: Annotated[AuditLogExportParams, Query()],
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
    _ensure_audit_read_permission(db, tenant_id, account_id)

    query = _build_audit_log_query(db, tenant_id=tenant_id, filters=export)
    query = _apply_export_cursor(query, AuditLog, after_created_at=export.after_created_at, after_id=export.after_id)
    rows = query.order_by(AuditLog.created_at.asc(), AuditLog.id.asc()).limit(export.limit).all()
    return _build_ndjson_streaming_response(
        _iter_audit_log_export_lines(rows, include_sensitive=export.include_sensitive),
        gzip_enabled=export.gzip,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/logs/purge", response_model=AuditLogPurgeResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def purge_audit_logs(
    params: Annotated[AuditLogPurgeParams, Query()],
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
    filter_values = params.model_dump(include=set(AuditLogFilterParams.model_fields))
    filter_payload = {name: value for name, value in filter_values.items() if value not in (None, "")}
    for name in ("since", "until"):
        if name in filter_payload:
            filter_payload[name] = filter_payload[name].isoformat()

    if params.purge_scope == "filtered" and not filter_payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one filter is required for filtered audit log purge",
        )

    cutoff = datetime.now(UTC) - timedelta(days=params.retention_days)
    if params.purge_scope == "filtered":
        eligible = plan_filtered_audit_log_purge(db, tenant_id=tenant_id, max_delete=params.max_delete, **filter_values)
    else:
        eligible = plan_audit_log_purge(db, tenant_id=tenant_id, cutoff=cutoff, max_delete=params.max_delete)

    deleted = 0
    if not params.dry_run:
        if params.purge_scope == "filtered":
            deleted = purge_filtered_audit_log_rows(
                db, tenant_id=tenant_id, max_delete=params.max_delete, commit=True, **filter_values
            )
        else:
            deleted = purge_audit_log_rows(
                db, tenant_id=tenant_id, cutoff=cutoff, max_delete=params.max_delete, commit=True
            )

    _record_audit_operation(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
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
        failure_message="Audit purge completed but its audit record failed",
    )
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
    missing = len(unique_ids) - deleted
    _record_audit_operation(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        action=action,
        resource_type="audit_logs",
        resource_id=str(unique_ids[0]) if len(unique_ids) == 1 else None,
        details={
            "requested": len(unique_ids),
            "deleted": deleted,
            "missing": missing,
            "ids": [str(value) for value in unique_ids[:50]],
        },
        failure_message="Audit deletion completed but its audit record failed",
    )
    return AuditLogDeleteResponse(requested=len(unique_ids), deleted=deleted, missing=missing, ids=unique_ids)


_ACCESS_GRAPH_RECORD_SCHEMA = "mimirq.access_graph_export_record.v1"
_ACCESS_GRAPH_PAGE_SCHEMA = "mimirq.access_graph_export_page.v1"
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
_ACCESS_GRAPH_KINDS = tuple(_ACCESS_GRAPH_MODELS)


def _hash16(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return stable_hash(normalized, length=16)


def _apply_export_cursor(
    query: ORMQuery, model: Any, *, after_created_at: datetime | None, after_id: UUID | None
) -> ORMQuery:
    if after_created_at is None:
        return query
    if after_id is not None:
        return query.filter(
            or_(
                model.created_at > after_created_at,
                and_(model.created_at == after_created_at, model.id > after_id),
            )
        )
    return query.filter(model.created_at > after_created_at)


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
                "name_hash": _hash16(name),
                "external_id": external_id if include_sensitive else None,
                "external_id_hash": _hash16(external_id),
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
                "user_id_hash": _hash16(user_id),
            }
        )
        return base

    if kind == "dataset":
        name = row.name
        owner_id = row.owner_id
        base.update(
            {
                "name": name if include_sensitive else None,
                "name_hash": _hash16(name),
                "permission": row.permission.value,
                "owner_id": owner_id if include_sensitive else None,
                "owner_id_hash": _hash16(owner_id),
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
                "account_id_hash": _hash16(account_id),
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
                "owner_id_hash": _hash16(owner_id),
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
                "account_id_hash": _hash16(account_id),
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

    raise ValueError(f"Unsupported access graph kind: {kind}")


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

    kind = after_kind.strip().lower() if after_kind is not None else None
    if kind == "":
        kind = None
    if (after_created_at is not None or after_id is not None) and not kind:
        raise HTTPException(status_code=400, detail="after_kind is required when using after_created_at/after_id")
    if kind is not None and kind not in _ACCESS_GRAPH_KINDS:
        raise HTTPException(status_code=400, detail=f"after_kind must be one of: {', '.join(_ACCESS_GRAPH_KINDS)}")
    return fmt, kind


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
    start = _ACCESS_GRAPH_KINDS.index(after_kind) if after_kind else 0
    records: list[dict[str, Any]] = []
    for kind in _ACCESS_GRAPH_KINDS[start:]:
        remaining = limit - len(records)
        if remaining == 0:
            break
        model = _ACCESS_GRAPH_MODELS[kind]
        query = db.query(model).filter(model.tenant_id == tenant_id)
        if kind == after_kind:
            query = _apply_export_cursor(query, model, after_created_at=after_created_at, after_id=after_id)
        rows = query.order_by(model.created_at.asc(), model.id.asc()).limit(remaining).all()
        records.extend(
            _export_access_graph_row(kind=kind, row=row, include_sensitive=include_sensitive) for row in rows
        )
    return records


def _access_graph_next_cursor(records: list[dict[str, Any]], *, limit: int) -> dict[str, Any] | None:
    if len(records) < limit:
        return None
    last = records[-1]
    return {
        "after_kind": last["kind"],
        "after_created_at": last["created_at"],
        "after_id": last["id"],
    }


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
    _ensure_audit_read_permission(db, tenant_id, account_id)
    fmt, kind = _normalize_access_graph_export_params(
        export_format=export_format,
        after_kind=after_kind,
        after_created_at=after_created_at,
        after_id=after_id,
    )
    records = _collect_access_graph_page(
        db,
        tenant_id=tenant_id,
        include_sensitive=include_sensitive,
        limit=limit,
        after_kind=kind,
        after_created_at=after_created_at,
        after_id=after_id,
    )
    next_cursor = _access_graph_next_cursor(records, limit=limit)
    _record_audit_operation(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        action="compliance.access_graph.export",
        resource_type="tenant",
        resource_id=str(tenant_id),
        details={
            "limit": limit,
            "returned": len(records),
            "after_kind": kind,
            "after_created_at": after_created_at.isoformat() if after_created_at else None,
            "after_id": str(after_id) if after_id else None,
            "include_sensitive": include_sensitive,
            "export_format": fmt,
            "gzip": gzip,
        },
        failure_message="Access graph export audit failed",
    )
    headers = _build_access_graph_headers(next_cursor)
    if fmt == "json":
        return _access_graph_json_response(
            limit=limit, out=records, next_cursor=next_cursor, headers=headers, gzip_enabled=gzip
        )
    return _build_ndjson_streaming_response(
        (
            (json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str) + "\n").encode("utf-8")
            for record in records
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
    _ensure_audit_read_permission(db, tenant_id, account_id)
    group_count = db.query(TenantGroup).filter(TenantGroup.tenant_id == tenant_id).count()
    group_member_count = db.query(TenantGroupMember).filter(TenantGroupMember.tenant_id == tenant_id).count()

    datasets = db.query(Dataset).filter(Dataset.tenant_id == tenant_id)
    dataset_count = datasets.count()
    dataset_permission_counts = {
        "all_team_members": datasets.filter(Dataset.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS).count(),
        "only_me": datasets.filter(Dataset.permission == DatasetPermissionEnum.ONLY_ME).count(),
        "partial_members": datasets.filter(Dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS).count(),
    }
    dataset_member_allowlist_count = (
        db.query(DatasetPermission).filter(DatasetPermission.tenant_id == tenant_id).count()
    )
    dataset_group_allowlist_count = (
        db.query(DatasetGroupPermission).filter(DatasetGroupPermission.tenant_id == tenant_id).count()
    )

    documents = db.query(Document).filter(Document.tenant_id == tenant_id)
    document_count = documents.count()
    doc_inherit_count = documents.filter(
        or_(Document.access_mode == None, Document.access_mode == "", Document.access_mode == "inherit")  # noqa: E711
    ).count()
    doc_partial_count = documents.filter(Document.access_mode == "partial_members").count()
    doc_only_me_count = documents.filter(Document.access_mode == "only_me").count()
    doc_all_team_count = documents.filter(Document.access_mode == "all_team_members").count()
    doc_known = doc_inherit_count + doc_partial_count + doc_only_me_count + doc_all_team_count
    document_access_mode_counts = {
        "inherit": doc_inherit_count,
        "partial_members": doc_partial_count,
        "only_me": doc_only_me_count,
        "all_team_members": doc_all_team_count,
        "unknown": max(0, document_count - doc_known),
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
    _record_audit_operation(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        action="compliance.access_graph.summary",
        resource_type="tenant",
        resource_id=str(tenant_id),
        details={
            "group_count": group_count,
            "group_member_count": group_member_count,
            "dataset_count": dataset_count,
            "document_count": document_count,
        },
        failure_message="Access graph summary audit failed",
    )
    return payload
