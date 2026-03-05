"""
SCIM v2 API (enterprise provisioning; opt-in).

Notes:
- Guarded behind `SCIM_ENABLED` and a static bearer token (`SCIM_BEARER_TOKEN`).
- Read-only initially: Users/Groups list + get.
- Optional: PATCH group membership (`SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED`).
"""

from __future__ import annotations

import contextlib
import re
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.dependencies.tenant import get_tenant_id
from app.core.config import settings
from app.core.database import get_db
from app.models.tenant import TenantMember
from app.services.audit_log_service import audit_log_event
from app.services.tenant_group_service import TenantGroupService

router = APIRouter()

_SCIM_MEDIA_TYPE = "application/scim+json"

_URN_LIST_RESPONSE = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
_URN_PATCH_OP = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
_URN_ERROR = "urn:ietf:params:scim:api:messages:2.0:Error"

_URN_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
_URN_GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
_URN_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Schema"
_URN_RESOURCE_TYPE = "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
_URN_SERVICE_PROVIDER_CONFIG = "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"

_REMOVE_MEMBER_FILTER_RE = re.compile(r'members\[\s*value\s+eq\s+"([^"]+)"\s*\]', re.IGNORECASE)


def _dt_iso(dt: Any) -> str | None:
    if not isinstance(dt, datetime):
        return None
    try:
        utc = dt.astimezone(timezone.utc)
    except Exception:
        utc = dt
    # SCIM examples commonly use RFC3339 with Z.
    return utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _scim_json(payload: dict[str, Any], *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=payload, media_type=_SCIM_MEDIA_TYPE)


def _scim_error(*, status_code: int, detail: str, scim_type: str | None = None) -> JSONResponse:
    out: dict[str, Any] = {"schemas": [_URN_ERROR], "status": str(int(status_code)), "detail": str(detail or "")}
    if scim_type:
        out["scimType"] = str(scim_type)
    return _scim_json(out, status_code=status_code)


def _require_scim_actor(authorization: str | None = Header(default=None)) -> str:
    if not bool(getattr(settings, "SCIM_ENABLED", False)):
        raise HTTPException(status_code=404, detail="SCIM not enabled")

    expected = str(getattr(settings, "SCIM_BEARER_TOKEN", "") or "").strip()
    if not expected:
        # Misconfiguration; do not expose further detail.
        raise HTTPException(status_code=404, detail="SCIM not enabled")

    auth = (authorization or "").strip()
    if not auth:
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = auth
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    else:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return "system:scim"


def _scim_page(*, start_index: int, count: int) -> tuple[int, int, int]:
    start = max(1, int(start_index or 1))
    page_size = max(1, int(count or 200))
    max_page_size = int(getattr(settings, "SCIM_PAGE_SIZE_MAX", 200) or 200)
    if max_page_size > 0:
        page_size = min(page_size, max_page_size)
    skip = start - 1
    return skip, page_size, start


def _list_response(*, resources: list[dict[str, Any]], total: int, start_index: int, items_per_page: int) -> dict[str, Any]:
    return {
        "schemas": [_URN_LIST_RESPONSE],
        "totalResults": int(total),
        "startIndex": int(start_index),
        "itemsPerPage": int(items_per_page),
        "Resources": resources,
    }


def _scim_user(member: TenantMember) -> dict[str, Any]:
    uid = str(getattr(member, "user_id", "") or "").strip()
    return {
        "schemas": [_URN_USER],
        "id": uid,
        "userName": uid,
        "active": bool(getattr(member, "is_current", False)),
        "meta": {
            "resourceType": "User",
            "created": _dt_iso(getattr(member, "created_at", None)),
            "lastModified": _dt_iso(getattr(member, "updated_at", None)),
        },
    }


def _scim_group(group: object, *, members: Iterable[str] | None = None, include_members: bool = False) -> dict[str, Any]:
    gid = str(getattr(group, "id", "") or "").strip()
    out: dict[str, Any] = {
        "schemas": [_URN_GROUP],
        "id": gid,
        "displayName": str(getattr(group, "name", "") or ""),
        "externalId": getattr(group, "external_id", None),
        "meta": {
            "resourceType": "Group",
            "created": _dt_iso(getattr(group, "created_at", None)),
            "lastModified": _dt_iso(getattr(group, "updated_at", None)),
        },
    }
    if include_members:
        mem_out: list[dict[str, Any]] = []
        for raw in members or []:
            uid = str(raw or "").strip()
            if not uid:
                continue
            mem_out.append({"value": uid, "display": uid})
            if len(mem_out) >= 2000:
                break
        out["members"] = mem_out
    return out


def _list_users(db: Session, *, tenant_id: UUID, skip: int, limit: int) -> tuple[int, list[TenantMember]]:
    q = (
        db.query(TenantMember)
        .filter(
            TenantMember.tenant_id == tenant_id,
            TenantMember.user_id.isnot(None),
            TenantMember.user_id != "",
        )
        .order_by(TenantMember.user_id.asc())
    )
    total = int(q.count())
    items = q.offset(max(0, int(skip or 0))).limit(max(1, min(int(limit or 0), 1000))).all()
    return total, items


def _get_user(db: Session, *, tenant_id: UUID, user_id: str) -> TenantMember | None:
    uid = str(user_id or "").strip()
    if not uid or len(uid) > 255:
        return None
    return (
        db.query(TenantMember)
        .filter(
            TenantMember.tenant_id == tenant_id,
            TenantMember.user_id == uid,
        )
        .first()
    )


@router.get("/ServiceProviderConfig")
def get_service_provider_config(_actor: str = Depends(_require_scim_actor)):
    # See RFC7644 §4 and RFC7643 (ServiceProviderConfig schema).
    patch_supported = bool(getattr(settings, "SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED", False))
    return _scim_json(
        {
            "schemas": [_URN_SERVICE_PROVIDER_CONFIG],
            "documentationUri": "https://datatracker.ietf.org/doc/html/rfc7644",
            "patch": {"supported": bool(patch_supported)},
            "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
            "filter": {"supported": False, "maxResults": 0},
            "changePassword": {"supported": False},
            "sort": {"supported": True},
            "etag": {"supported": False},
            "authenticationSchemes": [
                {
                    "type": "oauthbearertoken",
                    "name": "Bearer Token",
                    "description": "Static bearer token (SCIM_BEARER_TOKEN).",
                    "specUri": "https://datatracker.ietf.org/doc/html/rfc6750",
                    "primary": True,
                }
            ],
        }
    )


@router.get("/Schemas")
def list_schemas(_actor: str = Depends(_require_scim_actor)):
    # Minimal schema definitions (enough for discovery).
    user_schema = {
        "schemas": [_URN_SCHEMA],
        "id": _URN_USER,
        "name": "User",
        "description": "MimirQ SCIM user (maps to tenant_members.user_id).",
        "attributes": [
            {"name": "userName", "type": "string", "multiValued": False, "required": True},
            {"name": "active", "type": "boolean", "multiValued": False, "required": False},
        ],
    }
    group_schema = {
        "schemas": [_URN_SCHEMA],
        "id": _URN_GROUP,
        "name": "Group",
        "description": "MimirQ SCIM group (maps to tenant_groups).",
        "attributes": [
            {"name": "displayName", "type": "string", "multiValued": False, "required": True},
            {"name": "externalId", "type": "string", "multiValued": False, "required": False},
            {"name": "members", "type": "complex", "multiValued": True, "required": False},
        ],
    }
    resources = [user_schema, group_schema]
    return _scim_json(_list_response(resources=resources, total=len(resources), start_index=1, items_per_page=len(resources)))


@router.get("/ResourceTypes")
def list_resource_types(_actor: str = Depends(_require_scim_actor)):
    resources = [
        {
            "schemas": [_URN_RESOURCE_TYPE],
            "id": "User",
            "name": "User",
            "endpoint": "/Users",
            "schema": _URN_USER,
            "description": "Tenant users (read-only).",
        },
        {
            "schemas": [_URN_RESOURCE_TYPE],
            "id": "Group",
            "name": "Group",
            "endpoint": "/Groups",
            "schema": _URN_GROUP,
            "description": "Tenant groups (read-only; optional membership PATCH).",
        },
    ]
    return _scim_json(_list_response(resources=resources, total=len(resources), start_index=1, items_per_page=len(resources)))


@router.get("/Groups")
def list_groups(
    start_index: int = Query(default=1, ge=1, alias="startIndex"),
    count: int = Query(default=200, ge=1),
    tenant_id: UUID = Depends(get_tenant_id),
    _actor: str = Depends(_require_scim_actor),
    db: Session = Depends(get_db),
):
    skip, limit, start = _scim_page(start_index=start_index, count=count)
    total, groups = TenantGroupService.list_groups(db, tenant_id=tenant_id, skip=skip, limit=limit)
    resources = [_scim_group(g, include_members=False) for g in groups]
    return _scim_json(_list_response(resources=resources, total=total, start_index=start, items_per_page=len(resources)))


@router.get("/Groups/{group_id}")
def get_group(
    group_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    _actor: str = Depends(_require_scim_actor),
    db: Session = Depends(get_db),
):
    try:
        group = TenantGroupService.get_group(db, tenant_id=tenant_id, group_id=group_id)
        _total, rows = TenantGroupService.list_members(db, tenant_id=tenant_id, group_id=group_id, skip=0, limit=2000)
    except HTTPException as exc:
        return _scim_error(status_code=int(exc.status_code), detail=str(exc.detail or "error"))
    members = [str(getattr(r, "user_id", "") or "").strip() for r in rows]
    return _scim_json(_scim_group(group, include_members=True, members=members))


@router.get("/Users")
def list_users(
    start_index: int = Query(default=1, ge=1, alias="startIndex"),
    count: int = Query(default=200, ge=1),
    tenant_id: UUID = Depends(get_tenant_id),
    _actor: str = Depends(_require_scim_actor),
    db: Session = Depends(get_db),
):
    skip, limit, start = _scim_page(start_index=start_index, count=count)
    total, members = _list_users(db, tenant_id=tenant_id, skip=skip, limit=limit)
    resources = [_scim_user(m) for m in members]
    # Per SCIM, Resources are the only payload; keep it bounded.
    return _scim_json(_list_response(resources=resources, total=total, start_index=start, items_per_page=len(resources)))


@router.get("/Users/{user_id}")
def get_user(
    user_id: str,
    tenant_id: UUID = Depends(get_tenant_id),
    _actor: str = Depends(_require_scim_actor),
    db: Session = Depends(get_db),
):
    member = _get_user(db, tenant_id=tenant_id, user_id=user_id)
    if member is None:
        return _scim_error(status_code=404, detail="User not found")
    return _scim_json(_scim_user(member))


def _extract_member_ids(raw: Any) -> list[str]:
    # SCIM PATCH commonly sends either:
    # - value: [{"value": "alice"}, {"value": "bob"}]
    # - value: {"members": [{"value": "alice"}]}
    if raw is None:
        return []
    values = raw
    if isinstance(values, dict) and "members" in values:
        values = values.get("members")
    if isinstance(values, dict) and "value" in values:
        values = [values]
    if not isinstance(values, list):
        return []

    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, dict):
            continue
        uid = str(item.get("value") or "").strip()
        if not uid or uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
        if len(out) >= 200:
            break
    return out


@router.patch("/Groups/{group_id}")
def patch_group_membership(
    group_id: UUID,
    payload: dict[str, Any],
    tenant_id: UUID = Depends(get_tenant_id),
    actor_id: str = Depends(_require_scim_actor),
    db: Session = Depends(get_db),
):
    if not bool(getattr(settings, "SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED", False)):
        return _scim_error(status_code=404, detail="PATCH group membership not enabled")

    schemas = payload.get("schemas") if isinstance(payload, dict) else None
    if not isinstance(schemas, list) or _URN_PATCH_OP not in {str(s or "") for s in schemas}:
        return _scim_error(status_code=400, detail="Invalid SCIM PATCH payload", scim_type="invalidSyntax")

    ops = payload.get("Operations") if isinstance(payload, dict) else None
    if not isinstance(ops, list) or not ops:
        return _scim_error(status_code=400, detail="Missing Operations", scim_type="invalidSyntax")

    to_add: list[str] = []
    to_remove: list[str] = []
    for op in ops:
        if not isinstance(op, dict):
            continue
        op_name = str(op.get("op") or "").strip().lower()
        path = str(op.get("path") or "").strip()
        value = op.get("value")

        if op_name in {"add", "replace"} and (not path or path.lower().startswith("members")):
            to_add.extend(_extract_member_ids(value))
            continue

        if op_name == "remove" and path.lower().startswith("members"):
            extracted = _extract_member_ids(value)
            if extracted:
                to_remove.extend(extracted)
                continue
            m = _REMOVE_MEMBER_FILTER_RE.search(path)
            if m:
                uid = str(m.group(1) or "").strip()
                if uid:
                    to_remove.append(uid)

    # Idempotent: underlying service dedupes (add) and deletes only existing (remove).
    added = 0
    removed = 0
    try:
        if to_add:
            added = TenantGroupService.add_members(db, tenant_id=tenant_id, group_id=group_id, member_ids=to_add)
        if to_remove:
            removed = TenantGroupService.remove_members(db, tenant_id=tenant_id, group_id=group_id, member_ids=to_remove)
    except HTTPException as exc:
        return _scim_error(status_code=int(exc.status_code), detail=str(exc.detail or "error"))

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="scim.group.members.patch",
        resource_type="tenant_group",
        resource_id=str(group_id),
        details={
            "member_add_requested": int(len(to_add)),
            "member_remove_requested": int(len(to_remove)),
            "member_add_updated": int(added),
            "member_remove_updated": int(removed),
        },
    )
    with contextlib.suppress(Exception):
        db.commit()

    group = TenantGroupService.get_group(db, tenant_id=tenant_id, group_id=group_id)
    _total, rows = TenantGroupService.list_members(db, tenant_id=tenant_id, group_id=group_id, skip=0, limit=2000)
    members = [str(getattr(r, "user_id", "") or "").strip() for r in rows]
    return _scim_json(_scim_group(group, include_members=True, members=members))
