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
from app.core.constants import UserRoles
from app.core.database import get_db
from app.core.exceptions import MimirQError
from app.models.tenant import TenantMember
from app.models.tenant_group import TenantGroup, TenantGroupMember
from app.services import tenant_group_service
from app.services.audit_log_service import audit_log_event

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
    tenant_header = settings.TENANT_HEADER.strip() or "X-Tenant-ID"
    raw_tenant = (x_tenant_id or "").strip()
    if not raw_tenant and tenant_header.lower() != "x-tenant-id":
        raw_tenant = (request.headers.get(tenant_header) or "").strip()
    if not raw_tenant:
        raise HTTPException(status_code=400, detail=f"{tenant_header} header required")

    bound_tenant = settings.SCIM_TENANT_ID.strip()
    try:
        requested_id = UUID(raw_tenant)
        bound_id = UUID(bound_tenant)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid tenant id") from exc
    if requested_id != bound_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return bound_id


def _dt_iso(dt: datetime | None) -> str | None:
    if dt is None:
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
    out: dict[str, Any] = {"schemas": [_URN_ERROR], "status": str(status_code), "detail": detail}
    if scim_type:
        out["scimType"] = scim_type
    return _scim_json(out, status_code=status_code)


def _hash_pii(value: str | None) -> str:
    """Stable short hash for potentially sensitive identifiers."""
    raw = (value or "").strip().encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()[:16]


def _split_items(raw: str) -> list[str]:
    return [part for part in _TOKEN_SPLIT_RE.split(raw.strip()) if part]


def _token_matches(provided_token: str, expected_token: str) -> bool:
    expected = expected_token.strip()
    provided = provided_token.strip()
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
    key = raw.strip()
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
    if not settings.SCIM_ENABLED:
        raise HTTPException(status_code=404, detail="SCIM not enabled")

    expected_raw = settings.SCIM_BEARER_TOKEN.strip()
    expected_tokens = _split_items(expected_raw)
    if not expected_tokens:
        # Misconfiguration; do not expose further detail.
        raise HTTPException(status_code=404, detail="SCIM not enabled")

    allowlist_raw = settings.SCIM_IP_ALLOWLIST_CIDRS.strip()
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
    start = max(1, start_index)
    page_size = max(1, count or 200)
    max_page_size = settings.SCIM_PAGE_SIZE_MAX
    if max_page_size > 0:
        page_size = min(page_size, max_page_size)
    skip = start - 1
    return skip, page_size, start


def _list_response(
    *, resources: list[dict[str, Any]], total: int, start_index: int, items_per_page: int
) -> dict[str, Any]:
    return {
        "schemas": [_URN_LIST_RESPONSE],
        "totalResults": total,
        "startIndex": start_index,
        "itemsPerPage": items_per_page,
        "Resources": resources,
    }


def _scim_user(member: TenantMember) -> dict[str, Any]:
    uid = (member.user_id or "").strip()
    return {
        "schemas": [_URN_USER],
        "id": uid,
        "userName": uid,
        "active": bool(member.is_active),
        "meta": {
            "resourceType": "User",
            "created": _dt_iso(member.created_at),
            "lastModified": _dt_iso(member.updated_at),
        },
    }


def _scim_group(
    group: TenantGroup,
    *,
    members: Iterable[str] | None = None,
    include_members: bool = False,
) -> dict[str, Any]:
    gid = str(group.id)
    out: dict[str, Any] = {
        "schemas": [_URN_GROUP],
        "id": gid,
        "displayName": group.name,
        "externalId": group.external_id,
        "meta": {
            "resourceType": "Group",
            "created": _dt_iso(group.created_at),
            "lastModified": _dt_iso(group.updated_at),
        },
    }
    if include_members:
        mem_out: list[dict[str, Any]] = []
        for raw in members or ():
            uid = raw.strip()
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
    total = q.count()
    items = q.offset(max(0, skip)).limit(max(1, min(limit, 1000))).all()
    return total, items


def _get_user(db: Session, *, tenant_id: UUID, user_id: str) -> TenantMember | None:
    uid = user_id.strip()
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
def get_service_provider_config(_actor: Annotated[str, Depends(_require_scim_actor)]) -> JSONResponse:
    # See RFC7644 §4 and RFC7643 (ServiceProviderConfig schema).
    patch_supported = settings.SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED or settings.SCIM_USERS_PATCH_ACTIVE_ENABLED
    return _scim_json(
        {
            "schemas": [_URN_SERVICE_PROVIDER_CONFIG],
            "documentationUri": "https://datatracker.ietf.org/doc/html/rfc7644",
            "patch": {"supported": patch_supported},
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
def list_schemas(*, _actor: Annotated[str, Depends(_require_scim_actor)]) -> JSONResponse:
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
def list_resource_types(_actor: Annotated[str, Depends(_require_scim_actor)]) -> JSONResponse:
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
) -> JSONResponse:
    skip, limit, start = _scim_page(start_index=start_index, count=count)
    total, groups = tenant_group_service.list_groups(db, tenant_id=tenant_id, skip=skip, limit=limit)
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
) -> JSONResponse:
    try:
        return _group_response(db=db, tenant_id=tenant_id, group_id=group_id)
    except MimirQError as exc:
        return _scim_error(status_code=exc.status_code, detail=exc.message)


@router.post("/Groups", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def create_group(
    payload: dict[str, Any],
    http_request: Request,
    *,
    tenant_id: Annotated[UUID, Depends(get_scim_tenant_id)],
    actor_id: Annotated[str, Depends(_require_scim_actor)],
    db: Annotated[Session, Depends(get_db)],
) -> JSONResponse:
    if not settings.SCIM_GROUPS_MUTATION_ENABLED:
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
        if not isinstance(ext_raw, str):
            return _scim_error(status_code=400, detail="externalId must be a string", scim_type="invalidValue")
        external_id = ext_raw
        if len(external_id) > 255:
            return _scim_error(status_code=400, detail="externalId too long (max=255)", scim_type="invalidValue")

    try:
        group = tenant_group_service.create_group(db, tenant_id=tenant_id, name=display_name, external_id=external_id)
    except MimirQError as exc:
        scim_type = "uniqueness" if exc.status_code == 409 else None
        return _scim_error(status_code=exc.status_code, detail=exc.message, scim_type=scim_type)

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
        resource_id=str(group.id),
        http_request=http_request,
        details={
            "group_id": str(group.id),
            "display_name_hash": _hash_pii(display_name),
            "external_id_hash": _hash_pii(external_id) if external_id else None,
            "members_provided_count": member_count,
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
) -> JSONResponse:
    if not settings.SCIM_GROUPS_MUTATION_ENABLED:
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
        group = tenant_group_service.update_group(
            db,
            tenant_id=tenant_id,
            group_id=group_id,
            name=display_name,
            external_id=external_id_arg,
        )
    except MimirQError as exc:
        scim_type = "uniqueness" if exc.status_code == 409 else None
        return _scim_error(status_code=exc.status_code, detail=exc.message, scim_type=scim_type)

    _audit_scim(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="scim.group.put",
        resource_type="tenant_group",
        resource_id=str(group.id),
        http_request=http_request,
        details={
            "group_id": str(group.id),
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
) -> Response:
    if not settings.SCIM_GROUPS_MUTATION_ENABLED:
        return _scim_error(status_code=404, detail="DELETE /Groups not enabled")

    try:
        group = tenant_group_service.get_group(db, tenant_id=tenant_id, group_id=group_id)
    except MimirQError as exc:
        return _scim_error(status_code=exc.status_code, detail=exc.message)

    display_name = group.name
    external_id = group.external_id

    try:
        tenant_group_service.delete_group(db, tenant_id=tenant_id, group_id=group_id)
    except MimirQError as exc:
        return _scim_error(status_code=exc.status_code, detail=exc.message)

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
) -> JSONResponse:
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
) -> JSONResponse:
    member = _get_user(db, tenant_id=tenant_id, user_id=user_id)
    if member is None:
        return _scim_error(status_code=404, detail="User not found")
    return _scim_json(_scim_user(member))


def _coerce_bool(raw: object) -> bool | None:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        number = int(raw)
        if number in {0, 1}:
            return bool(number)
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
        request_id = getattr(http_request.state, "request_id", None)
        user_agent = http_request.headers.get("User-Agent")
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
    uid = user_id.strip()
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
    return deleted


@router.post("/Users", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def create_user(
    payload: dict[str, Any],
    http_request: Request,
    *,
    tenant_id: Annotated[UUID, Depends(get_scim_tenant_id)],
    actor_id: Annotated[str, Depends(_require_scim_actor)],
    db: Annotated[Session, Depends(get_db)],
) -> JSONResponse:
    if not settings.SCIM_USERS_CREATE_ENABLED:
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
        role=UserRoles.VIEWER,
        is_active=active,
        is_current=False,
    )
    db.add(member)

    user_id_hash = _hash_pii(user_name)
    _audit_scim(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="scim.user.create",
        resource_type="tenant_member",
        resource_id=user_id_hash,
        http_request=http_request,
        details={
            "user_id_hash": user_id_hash,
            "user_id_chars": len(user_name),
            "active": active,
        },
    )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _scim_error(status_code=409, detail="User already exists", scim_type="uniqueness")
    db.refresh(member)
    return _scim_json(_scim_user(member), status_code=201)


def _extract_active_patch(ops: object) -> bool | None:
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
) -> JSONResponse:
    if not settings.SCIM_USERS_PATCH_ACTIVE_ENABLED:
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

    before = bool(member.is_active)
    changed = before != desired
    member.is_active = desired
    if not desired:
        # Best-effort: inactive members should not be selected as "current".
        with contextlib.suppress(Exception):
            member.is_current = False

    revoked = 0
    if not desired and settings.SCIM_DEPROVISION_REVOKE_GROUP_MEMBERSHIPS_ENABLED:
        revoked = _revoke_group_memberships_for_user(
            db,
            tenant_id=tenant_id,
            user_id=member.user_id,
        )

    user_id_hash = _hash_pii(member.user_id)
    _audit_scim(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="scim.user.patch",
        resource_type="tenant_member",
        resource_id=user_id_hash,
        http_request=http_request,
        details={
            "user_id_hash": user_id_hash,
            "active_before": before,
            "active_after": desired,
            "changed": changed,
            "group_memberships_revoked": revoked,
        },
    )

    db.commit()
    db.refresh(member)
    return _scim_json(_scim_user(member))


def _extract_member_ids(raw: object) -> list[str]:
    # SCIM PATCH commonly sends either:
    # - value: [{"value": "alice"}, {"value": "bob"}]
    # - value: {"members": [{"value": "alice"}]}
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
                uid = m.group(1).strip()
                if uid:
                    to_remove.append(uid)
    return to_add, to_remove


def _group_response(*, db: Session, tenant_id: UUID, group_id: UUID) -> JSONResponse:
    group = tenant_group_service.get_group(db, tenant_id=tenant_id, group_id=group_id)
    _total, rows = tenant_group_service.list_members(db, tenant_id=tenant_id, group_id=group_id, skip=0, limit=2000)
    members = [row.user_id for row in rows]
    return _scim_json(_scim_group(group, include_members=True, members=members))


@router.patch("/Groups/{group_id}", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def patch_group_membership(
    group_id: UUID,
    payload: dict[str, Any],
    *,
    tenant_id: Annotated[UUID, Depends(get_scim_tenant_id)],
    actor_id: Annotated[str, Depends(_require_scim_actor)],
    db: Annotated[Session, Depends(get_db)],
) -> JSONResponse:
    if not settings.SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED:
        return _scim_error(status_code=404, detail="PATCH group membership not enabled")

    schemas = payload.get("schemas") if isinstance(payload, dict) else None
    if not isinstance(schemas, list) or _URN_PATCH_OP not in {str(s or "") for s in schemas}:
        return _scim_error(status_code=400, detail="Invalid SCIM PATCH payload", scim_type="invalidSyntax")

    ops = payload.get("Operations") if isinstance(payload, dict) else None
    if not isinstance(ops, list) or not ops:
        return _scim_error(status_code=400, detail="Missing Operations", scim_type="invalidSyntax")

    # Idempotent: underlying service dedupes (add) and deletes only existing (remove).
    to_add, to_remove = _membership_patch_targets(ops)
    added = 0
    removed = 0
    try:
        if to_add:
            added = tenant_group_service.add_members(db, tenant_id=tenant_id, group_id=group_id, member_ids=to_add)
        if to_remove:
            removed = tenant_group_service.remove_members(
                db,
                tenant_id=tenant_id,
                group_id=group_id,
                member_ids=to_remove,
            )
    except MimirQError as exc:
        return _scim_error(status_code=exc.status_code, detail=exc.message)

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="scim.group.members.patch",
        resource_type="tenant_group",
        resource_id=str(group_id),
        details={
            "member_add_requested": len(to_add),
            "member_remove_requested": len(to_remove),
            "member_add_updated": added,
            "member_remove_updated": removed,
        },
    )
    with contextlib.suppress(Exception):
        db.commit()

    return _group_response(db=db, tenant_id=tenant_id, group_id=group_id)
