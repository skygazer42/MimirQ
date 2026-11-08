"""
Tenant member auto-provisioning (enterprise).

Motivation:
- In AUTH_MODE=jwt deployments, a verified JWT may carry a tenant binding (JWT_TENANT_CLAIM).
- To support enterprise directory features (SCIM / tenant groups / ACLs), we want a
  tenant_members row to exist for the (tenant_id, user_id) pair.

Design:
- Opt-in via `JWT_TENANT_MEMBER_AUTO_PROVISION_ENABLED` (disabled by default).
- Tenant-safe: only provisions when a verified tenant UUID is present.
- Best-effort: never blocks auth flows; callers should swallow errors.
- PII-minimal audit: store hashes, not raw user ids.
"""

import contextlib
import hashlib
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.constants import UserRoles
from app.models.tenant import Tenant, TenantMember
from app.services.audit_log_service import audit_log_event


def ensure_tenant_member_for_jwt_user(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: str,
    actor_id: str = "system:jwt",
    request_id: str | None,
    ip: str | None,
    user_agent: str | None,
) -> bool:
    """
    Ensure a tenant_members row exists for (tenant_id, user_id).

    Returns True when a new row is created, False otherwise.
    """
    uid = user_id.strip()
    if not uid or len(uid) > 255:
        return False

    # Tenant-safe: only provision when the tenant exists.
    tenant_exists = db.query(Tenant).filter_by(id=tenant_id).first()
    if tenant_exists is None:
        return False

    existing = db.query(TenantMember).filter_by(tenant_id=tenant_id, user_id=uid).first()
    if existing is not None:
        return False

    member = TenantMember(
        tenant_id=tenant_id,
        user_id=uid,
        role=UserRoles.VIEWER,
        is_active=True,
        is_current=False,
    )
    db.add(member)

    user_id_hash = hashlib.sha256(uid.encode("utf-8", "ignore")).hexdigest()[:16]
    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id or "system:jwt",
        action="auth.jwt.tenant_member.auto_provision",
        resource_type="tenant_member",
        resource_id=user_id_hash,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
        details={
            "tenant_id": str(tenant_id),
            "user_id_hash": user_id_hash,
            "user_id_chars": len(uid),
            "role": UserRoles.VIEWER,
        },
    )
    return True


def maybe_auto_provision_jwt_tenant_member_best_effort(
    *,
    db_factory: Callable[[], Session],
    tenant_id: UUID,
    user_id: str,
    request_id: str | None,
    ip: str | None,
    user_agent: str | None,
) -> bool:
    """
    Best-effort wrapper that opens/closes a DB session.

    - `db_factory` is typically `SessionLocal`.
    - Returns True when a member is created; False otherwise.
    """
    db = db_factory()
    try:
        created = ensure_tenant_member_for_jwt_user(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            request_id=request_id,
            ip=ip,
            user_agent=user_agent,
        )
        if created:
            db.commit()
        return created
    except Exception:  # noqa: BLE001
        with contextlib.suppress(Exception):
            db.rollback()
        return False
    finally:
        with contextlib.suppress(Exception):
            db.close()


__all__ = [
    "ensure_tenant_member_for_jwt_user",
    "maybe_auto_provision_jwt_tenant_member_best_effort",
]
