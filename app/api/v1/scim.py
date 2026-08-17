"""
SCIM v2 API (enterprise provisioning; opt-in).

Notes:
- Guarded behind `SCIM_ENABLED` and bearer token auth (`SCIM_BEARER_TOKEN`).
- Defense-in-depth: optional IP allowlist (`SCIM_IP_ALLOWLIST_CIDRS`).
- Default read-only; write endpoints are separately opt-in:
  - Users: `SCIM_USERS_CREATE_ENABLED`, `SCIM_USERS_PATCH_ACTIVE_ENABLED`
  - Groups: `SCIM_GROUPS_MUTATION_ENABLED`
  - Group membership PATCH: `SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED`
- Token rotation: `SCIM_BEARER_TOKEN` may contain a comma/space-separated active set,
  and each token may be stored as raw or `sha256:<hex>` for safer config handling.
"""

import contextlib
import hashlib
import hmac
import ipaddress
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.tenant import TenantMember
from app.models.tenant_group import TenantGroupMember
from app.services.audit_log_service import audit_log_event
from app.services.tenant_group_service import TenantGroupService

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

_SCIM_MEDIA_TYPE = "application/scim+json"
_INVALID_SCIM_PAYLOAD_DETAIL = "Invalid SCIM payload"

_URN_LIST_RESPONSE = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
_URN_PATCH_OP = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
_URN_ERROR = "urn:ietf:params:scim:api:messages:2.0:Error"

_URN_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
_URN_GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
_URN_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Schema"
_URN_RESOURCE_TYPE = "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
_URN_SERVICE_PROVIDER_CONFIG = "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"

_TOKEN_SPLIT_RE = re.compile(r"[,\s]+")
_REMOVE_MEMBER_FILTER_RE = re.compile(r'members\[\s*value\s+eq\s+"([^"]+)"\s*\]', re.IGNORECASE)


def get_scim_tenant_id(request: Request, x_tenant_id: str | None = Header(default=None)) -> UUID:
    tenant_header = str(getattr(settings, "TENANT_HEADER", "") or "X-Tenant-ID").strip() or "X-Tenant-ID"
    raw_tenant = (x_tenant_id or "").strip()
    if not raw_tenant and tenant_header.lower() != "x-tenant-id":
        raw_tenant = (request.headers.get(tenant_header) or "").strip()
    if not raw_tenant:
        raise HTTPException(status_code=400, detail=f"{tenant_header} header required")

    bound_tenant = str(getattr(settings, "SCIM_TENANT_ID", "") or "").strip()
    try:
        requested_id = UUID(raw_tenant)
        bound_id = UUID(bound_tenant)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid tenant id") from exc
    if requested_id != bound_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return bound_id


def _dt_iso(dt: Any) -> str | None:
    if not isinstance(dt, datetime):
        return None
    try:
        utc = dt.astimezone(UTC)
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


def _hash_pii(value: object) -> str:
    """Stable short hash for potentially sensitive identifiers."""
    raw = str(value or "").strip().encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()[:16]


def _split_items(raw: object) -> list[str]:
    return [p for p in _TOKEN_SPLIT_RE.split(str(raw or "").strip()) if p]


def _token_matches(provided_token: str, expected_token: str) -> bool:
    expected = str(expected_token or "").strip()
    provided = str(provided_token or "").strip()
    if not expected or not provided:
        return False
    if expected.lower().startswith("sha256:"):
        digest = expected.split(":", 1)[1].strip().lower()
        if not digest:
            return False
        provided_digest = hashlib.sha256(provided.encode("utf-8", "ignore")).hexdigest()
        return hmac.compare_digest(provided_digest, digest)
    return hmac.compare_digest(provided, expected)


def _extract_client_ip(request: Request) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    candidate = request.client.host if request.client else ""
    if not candidate:
        return None
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


_allowlist_cache: dict[str, list[ipaddress.IPv4Network | ipaddress.IPv6Network]] = {}


def _parse_ip_allowlist(raw: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    key = str(raw or "").strip()
    if not key:
        return []
    cached = _allowlist_cache.get(key)
    if cached is not None:
        return cached
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for part in _split_items(key):
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            # Fail-closed behavior is handled by the caller (empty allowlist => deny all).
            continue
    _allowlist_cache[key] = nets
    return nets


def _require_scim_actor(request: Request, authorization: Annotated[str | None, Header()] = None) -> str:
    if not bool(getattr(settings, "SCIM_ENABLED", False)):
        raise HTTPException(status_code=404, detail="SCIM not enabled")

    expected_raw = str(getattr(settings, "SCIM_BEARER_TOKEN", "") or "").strip()
    expected_tokens = _split_items(expected_raw)
    if not expected_tokens:
        # Misconfiguration; do not expose further detail.
        raise HTTPException(status_code=404, detail="SCIM not enabled")

    allowlist_raw = str(getattr(settings, "SCIM_IP_ALLOWLIST_CIDRS", "") or "").strip()
    if allowlist_raw:
        client_ip = _extract_client_ip(request)
        if client_ip is None:
            raise HTTPException(status_code=403, detail="Forbidden")
        networks = _parse_ip_allowlist(allowlist_raw)
        if not networks or not any(client_ip in net for net in networks):
            raise HTTPException(status_code=403, detail="Forbidden")

    auth = (authorization or "").strip()
    if not auth:
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = auth
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    else:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not any(_token_matches(token, expected) for expected in expected_tokens):
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


def _list_response(
    *, resources: list[dict[str, Any]], total: int, start_index: int, items_per_page: int
) -> dict[str, Any]:
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
        "active": bool(getattr(member, "is_active", getattr(member, "is_current", False))),
        "meta": {
            "resourceType": "User",
            "created": _dt_iso(getattr(member, "created_at", None)),
            "lastModified": _dt_iso(getattr(member, "updated_at", None)),
        },
    }


def _scim_group(
    group: object,
    *,
    members: Iterable[str] | None = None,
    include_members: bool = False,
) -> dict[str, Any]:
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


@router.get("/ServiceProviderConfig", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_service_provider_config(_actor: Annotated[str, Depends(_require_scim_actor)]):
    # See RFC7644 §4 and RFC7643 (ServiceProviderConfig schema).
    patch_supported = bool(getattr(settings, "SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED", False)) or bool(
        getattr(settings, "SCIM_USERS_PATCH_ACTIVE_ENABLED", False)
    )
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


@router.get("/Schemas", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_schemas(*, _actor: Annotated[str, Depends(_require_scim_actor)]):
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
    return _scim_json(
        _list_response(
            resources=resources,
            total=len(resources),
            start_index=1,
            items_per_page=len(resources),
        )
    )


@router.get("/ResourceTypes", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_resource_types(_actor: Annotated[str, Depends(_require_scim_actor)]):
    resources = [
        {
            "schemas": [_URN_RESOURCE_TYPE],
            "id": "User",
            "name": "User",
            "endpoint": "/Users",
            "schema": _URN_USER,
            "description": "Tenant users (read; optional create/patch via flags).",
        },
        {
            "schemas": [_URN_RESOURCE_TYPE],
            "id": "Group",
            "name": "Group",
            "endpoint": "/Groups",
            "schema": _URN_GROUP,
            "description": "Tenant groups (read; optional mutate/membership PATCH via flags).",
        },
    ]
    return _scim_json(
        _list_response(
            resources=resources,
            total=len(resources),
            start_index=1,
            items_per_page=len(resources),
        )
    )


@router.get("/Groups", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_groups(
    start_index: Annotated[int, Query(ge=1, alias="startIndex")] = 1,
    count: Annotated[int, Query(ge=1)] = 200,
    *,
    tenant_id: Annotated[UUID, Depends(get_scim_tenant_id)],
    _actor: Annotated[str, Depends(_require_scim_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    skip, limit, start = _scim_page(start_index=start_index, count=count)
    total, groups = TenantGroupService.list_groups(db, tenant_id=tenant_id, skip=skip, limit=limit)
    resources = [_scim_group(g, include_members=False) for g in groups]
    return _scim_json(
        _list_response(
            resources=resources,
            total=total,
            start_index=start,
            items_per_page=len(resources),
        )
    )


@router.get("/Groups/{group_id}", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_group(
    group_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_scim_tenant_id)],
    _actor: Annotated[str, Depends(_require_scim_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    try:
        group = TenantGroupService.get_group(db, tenant_id=tenant_id, group_id=group_id)
        _total, rows = TenantGroupService.list_members(db, tenant_id=tenant_id, group_id=group_id, skip=0, limit=2000)
    except HTTPException as exc:
        return _scim_error(status_code=int(exc.status_code), detail=str(exc.detail or "error"))
    members = [str(getattr(r, "user_id", "") or "").strip() for r in rows]
    return _scim_json(_scim_group(group, include_members=True, members=members))


@router.post("/Groups", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def create_group(
    payload: dict[str, Any],
    http_request: Request,
    *,
    tenant_id: Annotated[UUID, Depends(get_scim_tenant_id)],
    actor_id: Annotated[str, Depends(_require_scim_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    if not bool(getattr(settings, "SCIM_GROUPS_MUTATION_ENABLED", False)):
        return _scim_error(status_code=404, detail="POST /Groups not enabled")

    if not isinstance(payload, dict):
        return _scim_error(status_code=400, detail=_INVALID_SCIM_PAYLOAD_DETAIL, scim_type="invalidSyntax")

    display_name = str(payload.get("displayName") or "").strip()
    if not display_name:
        return _scim_error(status_code=400, detail="displayName is required", scim_type="invalidValue")
    if len(display_name) > 255:
        return _scim_error(status_code=400, detail="displayName too long (max=255)", scim_type="invalidValue")

    ext_raw = payload.get("externalId", None)
    external_id = None
    if ext_raw is not None:
        external_id = str(ext_raw or "").strip() or None
        if external_id is not None and len(external_id) > 255:
            return _scim_error(status_code=400, detail="externalId too long (max=255)", scim_type="invalidValue")

    try:
        group = TenantGroupService.create_group(db, tenant_id=tenant_id, name=display_name, external_id=external_id)
    except HTTPException as exc:
        scim_type = "uniqueness" if int(exc.status_code) == 409 else None
        return _scim_error(status_code=int(exc.status_code), detail=str(exc.detail or "error"), scim_type=scim_type)

    members_provided = payload.get("members")
    member_count = 0
    if isinstance(members_provided, list):
        member_count = len(members_provided)

    _audit_scim(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="scim.group.create",
        resource_type="tenant_group",
        resource_id=str(getattr(group, "id", "") or ""),
        http_request=http_request,
        details={
            "group_id": str(getattr(group, "id", "") or ""),
            "display_name_hash": _hash_pii(display_name),
            "external_id_hash": _hash_pii(external_id) if external_id else None,
            "members_provided_count": int(member_count),
            "members_apply_via": "PATCH /Groups/{id} (SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED)",
        },
    )
    with contextlib.suppress(Exception):
        db.commit()

    return _scim_json(_scim_group(group, include_members=False), status_code=201)


@router.put("/Groups/{group_id}", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def put_group(
    group_id: UUID,
    payload: dict[str, Any],
    http_request: Request,
    *,
    tenant_id: Annotated[UUID, Depends(get_scim_tenant_id)],
    actor_id: Annotated[str, Depends(_require_scim_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    if not bool(getattr(settings, "SCIM_GROUPS_MUTATION_ENABLED", False)):
        return _scim_error(status_code=404, detail="PUT /Groups not enabled")

    if not isinstance(payload, dict):
        return _scim_error(status_code=400, detail=_INVALID_SCIM_PAYLOAD_DETAIL, scim_type="invalidSyntax")

    display_name = str(payload.get("displayName") or "").strip()
    if not display_name:
        return _scim_error(status_code=400, detail="displayName is required", scim_type="invalidValue")
    if len(display_name) > 255:
        return _scim_error(status_code=400, detail="displayName too long (max=255)", scim_type="invalidValue")

    # Only update externalId when explicitly provided. Allow clearing via "".
    external_id_arg: str | None = None
    external_id_hash: str | None = None
    if "externalId" in payload:
        raw_ext = str(payload.get("externalId") or "").strip()
        if len(raw_ext) > 255:
            return _scim_error(status_code=400, detail="externalId too long (max=255)", scim_type="invalidValue")
        external_id_arg = raw_ext  # may be "" to clear
        external_id_hash = _hash_pii(raw_ext) if raw_ext else None

    try:
        group = TenantGroupService.update_group(
            db,
            tenant_id=tenant_id,
            group_id=group_id,
            name=display_name,
            external_id=external_id_arg,
        )
    except HTTPException as exc:
        scim_type = "uniqueness" if int(exc.status_code) == 409 else None
        return _scim_error(status_code=int(exc.status_code), detail=str(exc.detail or "error"), scim_type=scim_type)

    _audit_scim(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="scim.group.put",
        resource_type="tenant_group",
        resource_id=str(getattr(group, "id", "") or ""),
        http_request=http_request,
        details={
            "group_id": str(getattr(group, "id", "") or ""),
            "display_name_hash": _hash_pii(display_name),
            "external_id_hash": external_id_hash,
        },
    )
    with contextlib.suppress(Exception):
        db.commit()

    return _scim_json(_scim_group(group, include_members=False))


@router.delete("/Groups/{group_id}", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def delete_group(
    group_id: UUID,
    http_request: Request,
    *,
    tenant_id: Annotated[UUID, Depends(get_scim_tenant_id)],
    actor_id: Annotated[str, Depends(_require_scim_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    if not bool(getattr(settings, "SCIM_GROUPS_MUTATION_ENABLED", False)):
        return _scim_error(status_code=404, detail="DELETE /Groups not enabled")

    try:
        group = TenantGroupService.get_group(db, tenant_id=tenant_id, group_id=group_id)
    except HTTPException as exc:
        return _scim_error(status_code=int(exc.status_code), detail=str(exc.detail or "error"))

    display_name = str(getattr(group, "name", "") or "")
    external_id = getattr(group, "external_id", None)

    try:
        TenantGroupService.delete_group(db, tenant_id=tenant_id, group_id=group_id)
    except HTTPException as exc:
        return _scim_error(status_code=int(exc.status_code), detail=str(exc.detail or "error"))

    _audit_scim(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="scim.group.delete",
        resource_type="tenant_group",
        resource_id=str(group_id),
        http_request=http_request,
        details={
            "group_id": str(group_id),
            "display_name_hash": _hash_pii(display_name),
            "external_id_hash": _hash_pii(external_id) if external_id else None,
        },
    )
    with contextlib.suppress(Exception):
        db.commit()

    return Response(status_code=204)


@router.get("/Users", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_users(
    start_index: Annotated[int, Query(ge=1, alias="startIndex")] = 1,
    count: Annotated[int, Query(ge=1)] = 200,
    *,
    tenant_id: Annotated[UUID, Depends(get_scim_tenant_id)],
    _actor: Annotated[str, Depends(_require_scim_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    skip, limit, start = _scim_page(start_index=start_index, count=count)
    total, members = _list_users(db, tenant_id=tenant_id, skip=skip, limit=limit)
    resources = [_scim_user(m) for m in members]
    # Per SCIM, Resources are the only payload; keep it bounded.
    return _scim_json(
        _list_response(
            resources=resources,
            total=total,
            start_index=start,
            items_per_page=len(resources),
        )
    )


@router.get("/Users/{user_id}", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_user(
    user_id: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_scim_tenant_id)],
    _actor: Annotated[str, Depends(_require_scim_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    member = _get_user(db, tenant_id=tenant_id, user_id=user_id)
    if member is None:
        return _scim_error(status_code=404, detail="User not found")
    return _scim_json(_scim_user(member))


def _coerce_bool(raw: Any) -> bool | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        if int(raw) in {0, 1}:
            return bool(int(raw))
        return None
    if isinstance(raw, str):
        v = raw.strip().lower()
        if v in {"true", "1", "yes", "y", "on"}:
            return True
        if v in {"false", "0", "no", "n", "off"}:
            return False
    return None


def _audit_scim(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    http_request: Request | None,
    details: dict[str, Any] | None = None,
) -> None:
    request_id = None
    ip = None
    user_agent = None
    if http_request is not None:
        request_id = str(getattr(http_request.state, "request_id", "") or "").strip() or None
        user_agent = (http_request.headers.get("User-Agent") or "").strip() or None
        with contextlib.suppress(Exception):
            parsed_ip = _extract_client_ip(http_request)
            ip = str(parsed_ip) if parsed_ip is not None else None

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
        details=details,
    )


def _revoke_group_memberships_for_user(db: Session, *, tenant_id: UUID, user_id: str) -> int:
    """
    Best-effort deprovisioning primitive: remove all group memberships for a user.

    Caller decides whether to commit (we intentionally do not commit here).
    """
    uid = str(user_id or "").strip()
    if not uid or len(uid) > 255:
        return 0
    deleted = (
        db.query(TenantGroupMember)
        .filter(
            TenantGroupMember.tenant_id == tenant_id,
            TenantGroupMember.user_id == uid,
        )
        .delete(synchronize_session=False)
    )
    return int(deleted or 0)


@router.post("/Users", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def create_user(
    payload: dict[str, Any],
    http_request: Request,
    *,
    tenant_id: Annotated[UUID, Depends(get_scim_tenant_id)],
    actor_id: Annotated[str, Depends(_require_scim_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    if not bool(getattr(settings, "SCIM_USERS_CREATE_ENABLED", False)):
        return _scim_error(status_code=404, detail="POST /Users not enabled")

    if not isinstance(payload, dict):
        return _scim_error(status_code=400, detail=_INVALID_SCIM_PAYLOAD_DETAIL, scim_type="invalidSyntax")

    user_name = str(payload.get("userName") or "").strip()
    if not user_name:
        return _scim_error(status_code=400, detail="userName is required", scim_type="invalidValue")
    if len(user_name) > 255:
        return _scim_error(status_code=400, detail="userName too long (max=255)", scim_type="invalidValue")

    raw_active = payload.get("active", None)
    active = _coerce_bool(raw_active)
    if raw_active is not None and active is None:
        return _scim_error(status_code=400, detail="active must be boolean", scim_type="invalidValue")
    if active is None:
        active = True

    existing = _get_user(db, tenant_id=tenant_id, user_id=user_name)
    if existing is not None:
        return _scim_error(status_code=409, detail="User already exists", scim_type="uniqueness")

    member = TenantMember(
        tenant_id=tenant_id,
        user_id=user_name,
        role="viewer",
        is_active=bool(active),
        is_current=False,
    )
    db.add(member)

    _audit_scim(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="scim.user.create",
        resource_type="tenant_member",
        resource_id=_hash_pii(user_name),
        http_request=http_request,
        details={
            "user_id_hash": _hash_pii(user_name),
            "user_id_chars": int(len(user_name)),
            "active": bool(active),
        },
    )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _scim_error(status_code=409, detail="User already exists", scim_type="uniqueness")
    db.refresh(member)
    return _scim_json(_scim_user(member), status_code=201)


def _extract_active_patch(ops: Any) -> bool | None:
    if not isinstance(ops, list) or not ops:
        return None
    desired: bool | None = None
    for raw in ops:
        if not isinstance(raw, dict):
            continue
        op = str(raw.get("op") or "").strip().lower()
        path = str(raw.get("path") or "").strip().lower()
        value = raw.get("value")

        # Common pattern: {"op":"Replace","path":"active","value":false}
        if path == "active":
            if op in {"add", "replace"}:
                desired = _coerce_bool(value)
            elif op == "remove":
                desired = False
            continue

        # Alternate pattern: {"op":"Replace","value":{"active":false}}
        if not path and isinstance(value, dict) and "active" in value and op in {"add", "replace"}:
            desired = _coerce_bool(value.get("active"))

    return desired


@router.patch("/Users/{user_id}", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def patch_user(
    user_id: str,
    payload: dict[str, Any],
    http_request: Request,
    *,
    tenant_id: Annotated[UUID, Depends(get_scim_tenant_id)],
    actor_id: Annotated[str, Depends(_require_scim_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    if not bool(getattr(settings, "SCIM_USERS_PATCH_ACTIVE_ENABLED", False)):
        return _scim_error(status_code=404, detail="PATCH /Users not enabled")

    member = _get_user(db, tenant_id=tenant_id, user_id=user_id)
    if member is None:
        return _scim_error(status_code=404, detail="User not found")

    schemas = payload.get("schemas") if isinstance(payload, dict) else None
    if not isinstance(schemas, list) or _URN_PATCH_OP not in {str(s or "") for s in schemas}:
        return _scim_error(status_code=400, detail="Invalid SCIM PATCH payload", scim_type="invalidSyntax")

    ops = payload.get("Operations") if isinstance(payload, dict) else None
    desired = _extract_active_patch(ops)
    if desired is None:
        return _scim_error(status_code=400, detail="Only 'active' PATCH is supported", scim_type="invalidPath")

    before = bool(getattr(member, "is_active", True))
    after = bool(desired)
    changed = before != after
    member.is_active = after
    if not after:
        # Best-effort: inactive members should not be selected as "current".
        with contextlib.suppress(Exception):
            member.is_current = False

    revoked = 0
    if not after and bool(getattr(settings, "SCIM_DEPROVISION_REVOKE_GROUP_MEMBERSHIPS_ENABLED", False)):
        revoked = _revoke_group_memberships_for_user(
            db,
            tenant_id=tenant_id,
            user_id=str(getattr(member, "user_id", user_id) or ""),
        )

    _audit_scim(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="scim.user.patch",
        resource_type="tenant_member",
        resource_id=_hash_pii(getattr(member, "user_id", user_id)),
        http_request=http_request,
        details={
            "user_id_hash": _hash_pii(getattr(member, "user_id", user_id)),
            "active_before": bool(before),
            "active_after": bool(after),
            "changed": bool(changed),
            "group_memberships_revoked": int(revoked),
        },
    )

    db.commit()
    db.refresh(member)
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


def _validate_group_membership_patch_payload(payload: dict[str, Any]) -> tuple[list[Any] | None, JSONResponse | None]:
    schemas = payload.get("schemas") if isinstance(payload, dict) else None
    if not isinstance(schemas, list) or _URN_PATCH_OP not in {str(s or "") for s in schemas}:
        return None, _scim_error(status_code=400, detail="Invalid SCIM PATCH payload", scim_type="invalidSyntax")

    ops = payload.get("Operations") if isinstance(payload, dict) else None
    if not isinstance(ops, list) or not ops:
        return None, _scim_error(status_code=400, detail="Missing Operations", scim_type="invalidSyntax")
    return ops, None


def _membership_patch_targets(ops: list[Any]) -> tuple[list[str], list[str]]:
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
    return to_add, to_remove


def _apply_membership_patch(
    *,
    db: Session,
    tenant_id: UUID,
    group_id: UUID,
    to_add: list[str],
    to_remove: list[str],
) -> tuple[int, int] | JSONResponse:
    added = 0
    removed = 0
    try:
        if to_add:
            added = TenantGroupService.add_members(db, tenant_id=tenant_id, group_id=group_id, member_ids=to_add)
        if to_remove:
            removed = TenantGroupService.remove_members(
                db,
                tenant_id=tenant_id,
                group_id=group_id,
                member_ids=to_remove,
            )
    except HTTPException as exc:
        return _scim_error(status_code=int(exc.status_code), detail=str(exc.detail or "error"))
    return added, removed


def _audit_membership_patch(
    *,
    db: Session,
    tenant_id: UUID,
    actor_id: str,
    group_id: UUID,
    to_add: list[str],
    to_remove: list[str],
    added: int,
    removed: int,
) -> None:
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


def _membership_patch_response(*, db: Session, tenant_id: UUID, group_id: UUID) -> JSONResponse:
    group = TenantGroupService.get_group(db, tenant_id=tenant_id, group_id=group_id)
    _total, rows = TenantGroupService.list_members(db, tenant_id=tenant_id, group_id=group_id, skip=0, limit=2000)
    members = [str(getattr(r, "user_id", "") or "").strip() for r in rows]
    return _scim_json(_scim_group(group, include_members=True, members=members))


@router.patch("/Groups/{group_id}", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def patch_group_membership(
    group_id: UUID,
    payload: dict[str, Any],
    *,
    tenant_id: Annotated[UUID, Depends(get_scim_tenant_id)],
    actor_id: Annotated[str, Depends(_require_scim_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    if not bool(getattr(settings, "SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED", False)):
        return _scim_error(status_code=404, detail="PATCH group membership not enabled")

    ops, error = _validate_group_membership_patch_payload(payload)
    if error is not None:
        return error

    # Idempotent: underlying service dedupes (add) and deletes only existing (remove).
    to_add, to_remove = _membership_patch_targets(ops or [])
    applied = _apply_membership_patch(
        db=db,
        tenant_id=tenant_id,
        group_id=group_id,
        to_add=to_add,
        to_remove=to_remove,
    )
    if isinstance(applied, JSONResponse):
        return applied
    added, removed = applied

    _audit_membership_patch(
        db=db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        group_id=group_id,
        to_add=to_add,
        to_remove=to_remove,
        added=added,
        removed=removed,
    )
    with contextlib.suppress(Exception):
        db.commit()

    return _membership_patch_response(db=db, tenant_id=tenant_id, group_id=group_id)
