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

from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.config import settings
from app.core.constants import UserRoles
from app.core.database import get_db
from app.core.exceptions import MimirQError
from app.models.tenant import TenantMember
from app.models.tenant_group import TenantGroup, TenantGroupMember
from app.rag.core.logging import get_logger
from app.services import tenant_group_service
from app.services.audit_log_service import audit_log_event

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger(__name__)

_SCIM_MEDIA_TYPE = "application/scim+json"

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


def get_scim_tenant_id(request: Request, x_tenant_id: Annotated[str | None, Header()] = None) -> UUID:
    tenant_header = settings.TENANT_HEADER.strip() or "X-Tenant-ID"
    raw_tenant = x_tenant_id.strip() if x_tenant_id is not None else None
    if not raw_tenant and tenant_header.lower() != "x-tenant-id":
        raw_tenant = request.headers.get(tenant_header)
        if raw_tenant is not None:
            raw_tenant = raw_tenant.strip()
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


def _scim_timestamp(timestamp: datetime | None) -> str | None:
    if timestamp is None:
        return None
    return timestamp.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _scim_json(payload: dict[str, Any], *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=payload, media_type=_SCIM_MEDIA_TYPE)


def _scim_error(*, status_code: int, detail: str, scim_type: str | None = None) -> JSONResponse:
    payload: dict[str, Any] = {"schemas": [_URN_ERROR], "status": str(status_code), "detail": detail}
    if scim_type:
        payload["scimType"] = scim_type
    return _scim_json(payload, status_code=status_code)


def _hash_pii(value: str) -> str:
    """Stable short hash for potentially sensitive identifiers."""
    raw = value.strip().encode("utf-8", "ignore")
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
    candidate = request.client.host if request.client else None
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
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for cidr in _split_items(key):
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            # Fail-closed behavior is handled by the caller (empty allowlist => deny all).
            continue
    _allowlist_cache[key] = networks
    return networks


def _require_scim_actor(request: Request, authorization: Annotated[str | None, Header()] = None) -> str:
    if not settings.SCIM_ENABLED:
        raise HTTPException(status_code=404, detail="SCIM not enabled")

    expected_tokens = _split_items(settings.SCIM_BEARER_TOKEN)
    if not expected_tokens:
        # Misconfiguration; do not expose further detail.
        raise HTTPException(status_code=404, detail="SCIM not enabled")

    allowlist_raw = settings.SCIM_IP_ALLOWLIST_CIDRS.strip()
    if allowlist_raw:
        client_ip = _extract_client_ip(request)
        if client_ip is None:
            raise HTTPException(status_code=403, detail="Forbidden")
        networks = _parse_ip_allowlist(allowlist_raw)
        if not any(client_ip in network for network in networks):
            raise HTTPException(status_code=403, detail="Forbidden")

    if authorization is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not any(_token_matches(token, expected) for expected in expected_tokens):
        raise HTTPException(status_code=401, detail="Unauthorized")

    return "system:scim"


def _scim_page(*, start_index: int, count: int) -> tuple[int, int, int]:
    page_size = min(count, settings.SCIM_PAGE_SIZE_MAX)
    return start_index - 1, page_size, start_index


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
    user_id = member.user_id.strip()
    return {
        "schemas": [_URN_USER],
        "id": user_id,
        "userName": user_id,
        "active": bool(member.is_active),
        "meta": {
            "resourceType": "User",
            "created": _scim_timestamp(member.created_at),
            "lastModified": _scim_timestamp(member.updated_at),
        },
    }


def _scim_group(
    group: TenantGroup,
    *,
    members: Iterable[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schemas": [_URN_GROUP],
        "id": str(group.id),
        "displayName": group.name,
        "externalId": group.external_id,
        "meta": {
            "resourceType": "Group",
            "created": _scim_timestamp(group.created_at),
            "lastModified": _scim_timestamp(group.updated_at),
        },
    }
    if members is None:
        return payload

    serialized_members: list[dict[str, str]] = []
    for member_id in members:
        user_id = member_id.strip()
        if not user_id:
            continue
        serialized_members.append({"value": user_id, "display": user_id})
        if len(serialized_members) >= 2000:
            break
    payload["members"] = serialized_members
    return payload


def _list_users(db: Session, *, tenant_id: UUID, skip: int, limit: int) -> tuple[int, list[TenantMember]]:
    query = (
        db.query(TenantMember)
        .filter(
            TenantMember.tenant_id == tenant_id,
            TenantMember.user_id.isnot(None),
            TenantMember.user_id != "",
        )
        .order_by(TenantMember.user_id.asc())
    )
    total = query.count()
    items = query.offset(skip).limit(min(limit, 1000)).all()
    return total, items


def _get_user(db: Session, *, tenant_id: UUID, user_id: str) -> TenantMember | None:
    user_id = user_id.strip()
    if not user_id or len(user_id) > 255:
        return None
    return (
        db.query(TenantMember)
        .filter(
            TenantMember.tenant_id == tenant_id,
            TenantMember.user_id == user_id,
        )
        .first()
    )


@router.get("/ServiceProviderConfig")
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


@router.get("/Schemas")
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


@router.get("/ResourceTypes")
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


@router.get("/Groups")
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
    resources = [_scim_group(group) for group in groups]
    return _scim_json(
        _list_response(
            resources=resources,
            total=total,
            start_index=start,
            items_per_page=len(resources),
        )
    )


@router.get("/Groups/{group_id}")
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


@router.post("/Groups")
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

    display_name = payload.get("displayName")
    if not isinstance(display_name, str) or not display_name.strip():
        return _scim_error(status_code=400, detail="displayName is required", scim_type="invalidValue")
    display_name = display_name.strip()
    if len(display_name) > 255:
        return _scim_error(status_code=400, detail="displayName too long (max=255)", scim_type="invalidValue")

    external_id = payload.get("externalId")
    if external_id is not None:
        if not isinstance(external_id, str):
            return _scim_error(status_code=400, detail="externalId must be a string", scim_type="invalidValue")
        if len(external_id) > 255:
            return _scim_error(status_code=400, detail="externalId too long (max=255)", scim_type="invalidValue")

    try:
        group = tenant_group_service.create_group(db, tenant_id=tenant_id, name=display_name, external_id=external_id)
    except MimirQError as exc:
        scim_type = "uniqueness" if exc.status_code == 409 else None
        return _scim_error(status_code=exc.status_code, detail=exc.message, scim_type=scim_type)

    members_provided = payload.get("members")
    member_count = len(members_provided) if isinstance(members_provided, list) else 0

    response = _scim_json(_scim_group(group), status_code=201)
    _commit_scim_audit(
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
    return response


@router.put("/Groups/{group_id}")
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

    display_name = payload.get("displayName")
    if not isinstance(display_name, str) or not display_name.strip():
        return _scim_error(status_code=400, detail="displayName is required", scim_type="invalidValue")
    display_name = display_name.strip()
    if len(display_name) > 255:
        return _scim_error(status_code=400, detail="displayName too long (max=255)", scim_type="invalidValue")

    # Only update externalId when explicitly provided. Allow clearing via "".
    external_id: str | None = None
    if "externalId" in payload:
        external_id = payload["externalId"]
        if external_id is None:
            external_id = ""
        if not isinstance(external_id, str):
            return _scim_error(status_code=400, detail="externalId must be a string", scim_type="invalidValue")
        external_id = external_id.strip()
        if len(external_id) > 255:
            return _scim_error(status_code=400, detail="externalId too long (max=255)", scim_type="invalidValue")

    try:
        group = tenant_group_service.update_group(
            db,
            tenant_id=tenant_id,
            group_id=group_id,
            name=display_name,
            external_id=external_id,
        )
    except MimirQError as exc:
        scim_type = "uniqueness" if exc.status_code == 409 else None
        return _scim_error(status_code=exc.status_code, detail=exc.message, scim_type=scim_type)

    response = _scim_json(_scim_group(group))
    _commit_scim_audit(
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
            "external_id_hash": _hash_pii(external_id) if external_id else None,
        },
    )
    return response


@router.delete("/Groups/{group_id}")
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
        display_name = group.name
        external_id = group.external_id
        tenant_group_service.delete_group(db, tenant_id=tenant_id, group_id=group_id)
    except MimirQError as exc:
        return _scim_error(status_code=exc.status_code, detail=exc.message)

    _commit_scim_audit(
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
    return Response(status_code=204)


@router.get("/Users")
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
    resources = [_scim_user(member) for member in members]
    # Per SCIM, Resources are the only payload; keep it bounded.
    return _scim_json(
        _list_response(
            resources=resources,
            total=total,
            start_index=start,
            items_per_page=len(resources),
        )
    )


@router.get("/Users/{user_id}")
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
        normalized = raw.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    return None


def _commit_scim_audit(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    http_request: Request | None,
    details: dict[str, Any],
) -> None:
    """Commit the audit after the business operation, without undoing that operation on audit failure."""
    try:
        request_id = None
        ip = None
        user_agent = None
        if http_request is not None:
            request_id = getattr(http_request.state, "request_id", None)
            user_agent = http_request.headers.get("User-Agent")
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
        db.commit()
    except Exception:
        logger.warning(
            "SCIM operation committed but audit logging failed: action=%s resource_id=%s",
            action,
            resource_id,
            exc_info=True,
        )
        db.rollback()


def _revoke_group_memberships_for_user(db: Session, *, tenant_id: UUID, user_id: str) -> int:
    """Remove memberships in the user's tenant; the caller owns the transaction."""
    return (
        db.query(TenantGroupMember)
        .filter(
            TenantGroupMember.tenant_id == tenant_id,
            TenantGroupMember.user_id == user_id.strip(),
        )
        .delete(synchronize_session=False)
    )


@router.post("/Users")
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

    user_name = payload.get("userName")
    if not isinstance(user_name, str) or not user_name.strip():
        return _scim_error(status_code=400, detail="userName is required", scim_type="invalidValue")
    user_name = user_name.strip()
    if len(user_name) > 255:
        return _scim_error(status_code=400, detail="userName too long (max=255)", scim_type="invalidValue")

    raw_active = payload.get("active")
    active = True if raw_active is None else _coerce_bool(raw_active)
    if active is None:
        return _scim_error(status_code=400, detail="active must be boolean", scim_type="invalidValue")

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
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _scim_error(status_code=409, detail="User already exists", scim_type="uniqueness")
    db.refresh(member)
    response = _scim_json(_scim_user(member), status_code=201)

    user_id_hash = _hash_pii(user_name)
    _commit_scim_audit(
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

    return response


def _extract_active_patch(ops: object) -> bool | None:
    if not isinstance(ops, list) or not ops:
        return None
    desired: bool | None = None
    for operation in ops:
        if not isinstance(operation, dict):
            continue
        operation_name = operation.get("op")
        path = operation.get("path")
        if not isinstance(operation_name, str) or (path is not None and not isinstance(path, str)):
            continue
        operation_name = operation_name.strip().lower()
        if path is not None:
            path = path.strip().lower()
        value = operation.get("value")

        # Common pattern: {"op":"Replace","path":"active","value":false}
        if path == "active":
            if operation_name in {"add", "replace"}:
                desired = _coerce_bool(value)
            elif operation_name == "remove":
                desired = False
            continue

        # Alternate pattern: {"op":"Replace","value":{"active":false}}
        if not path and isinstance(value, dict) and "active" in value and operation_name in {"add", "replace"}:
            desired = _coerce_bool(value["active"])

    return desired


@router.patch("/Users/{user_id}")
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

    schemas = payload.get("schemas")
    if (
        not isinstance(schemas, list)
        or any(not isinstance(schema, str) for schema in schemas)
        or _URN_PATCH_OP not in schemas
    ):
        return _scim_error(status_code=400, detail="Invalid SCIM PATCH payload", scim_type="invalidSyntax")

    ops = payload.get("Operations")
    desired = _extract_active_patch(ops)
    if desired is None:
        return _scim_error(status_code=400, detail="Only 'active' PATCH is supported", scim_type="invalidPath")

    before = bool(member.is_active)
    changed = before != desired
    member.is_active = desired
    if not desired:
        member.is_current = False

    revoked = 0
    if not desired and settings.SCIM_DEPROVISION_REVOKE_GROUP_MEMBERSHIPS_ENABLED:
        revoked = _revoke_group_memberships_for_user(
            db,
            tenant_id=tenant_id,
            user_id=member.user_id,
        )

    db.commit()
    db.refresh(member)
    response = _scim_json(_scim_user(member))
    user_id_hash = _hash_pii(member.user_id)
    _commit_scim_audit(
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

    return response


def _extract_member_ids(raw: object) -> list[str]:
    # SCIM PATCH commonly sends either:
    # - value: [{"value": "alice"}, {"value": "bob"}]
    # - value: {"members": [{"value": "alice"}]}
    values = raw
    if isinstance(values, dict) and "members" in values:
        values = values["members"]
    if isinstance(values, dict) and "value" in values:
        values = [values]
    if not isinstance(values, list):
        return []

    member_ids: list[str] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, dict):
            continue
        user_id = item.get("value")
        if not isinstance(user_id, str):
            continue
        user_id = user_id.strip()
        if not user_id or user_id in seen:
            continue
        seen.add(user_id)
        member_ids.append(user_id)
        if len(member_ids) >= 200:
            break
    return member_ids


def _membership_patch_targets(ops: list[Any]) -> tuple[list[str], list[str]]:
    to_add: list[str] = []
    to_remove: list[str] = []
    for operation in ops:
        if not isinstance(operation, dict):
            continue
        operation_name = operation.get("op")
        path = operation.get("path")
        if not isinstance(operation_name, str) or (path is not None and not isinstance(path, str)):
            continue
        operation_name = operation_name.strip().lower()
        if path is not None:
            path = path.strip()
        value = operation.get("value")

        if operation_name in {"add", "replace"} and (not path or path.lower().startswith("members")):
            to_add.extend(_extract_member_ids(value))
            continue

        if operation_name == "remove" and path is not None and path.lower().startswith("members"):
            extracted = _extract_member_ids(value)
            if extracted:
                to_remove.extend(extracted)
                continue
            member_filter_match = _REMOVE_MEMBER_FILTER_RE.search(path)
            if member_filter_match:
                user_id = member_filter_match.group(1).strip()
                if user_id:
                    to_remove.append(user_id)
    return to_add, to_remove


def _group_response(*, db: Session, tenant_id: UUID, group_id: UUID) -> JSONResponse:
    group = tenant_group_service.get_group(db, tenant_id=tenant_id, group_id=group_id)
    _total, rows = tenant_group_service.list_members(db, tenant_id=tenant_id, group_id=group_id, skip=0, limit=2000)
    members = [row.user_id for row in rows]
    return _scim_json(_scim_group(group, members=members))


@router.patch("/Groups/{group_id}")
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

    schemas = payload.get("schemas")
    if (
        not isinstance(schemas, list)
        or any(not isinstance(schema, str) for schema in schemas)
        or _URN_PATCH_OP not in schemas
    ):
        return _scim_error(status_code=400, detail="Invalid SCIM PATCH payload", scim_type="invalidSyntax")

    ops = payload.get("Operations")
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

    response = _group_response(db=db, tenant_id=tenant_id, group_id=group_id)
    _commit_scim_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="scim.group.members.patch",
        resource_type="tenant_group",
        resource_id=str(group_id),
        http_request=None,
        details={
            "member_add_requested": len(to_add),
            "member_remove_requested": len(to_remove),
            "member_add_updated": added,
            "member_remove_updated": removed,
        },
    )
    return response
