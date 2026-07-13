"""
Tenant-scoped RBAC utilities.

Centralizes role/permission checks so API endpoints avoid ad-hoc role sets.
"""


from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.constants import UserRoles
from app.models.tenant import TenantMember
from app.services.dataset_service import DatasetService


class TenantPermissions:
    """Permission constants (tenant-scoped)."""

    SETTINGS_READ = "settings.read"
    SETTINGS_WRITE = "settings.write"
    OBSERVABILITY_READ = "observability.read"
    USAGE_READ = "usage.read"
    AUDIT_READ = "audit.read"
    AUDIT_MANAGE = "audit.manage"
    TABLE_SQL_READ = "table_sql.read"
    LIFECYCLE_MANAGE = "lifecycle.manage"
    FEEDBACK_TRIAGE_WRITE = "feedback_triage.write"


def _normalize_role(role: object) -> str:
    return str(role or "").strip().lower()


_AUDITOR_ROLES: frozenset[str] = frozenset({UserRoles.OWNER, UserRoles.ADMIN, UserRoles.AUDITOR})
_ADMIN_ROLES: frozenset[str] = frozenset(UserRoles.ADMIN_ROLES)

_PERMISSION_ROLES: dict[str, frozenset[str]] = {
    TenantPermissions.SETTINGS_READ: _ADMIN_ROLES,
    TenantPermissions.SETTINGS_WRITE: _ADMIN_ROLES,
    TenantPermissions.OBSERVABILITY_READ: _ADMIN_ROLES,
    TenantPermissions.USAGE_READ: _ADMIN_ROLES,
    TenantPermissions.AUDIT_READ: _AUDITOR_ROLES,
    TenantPermissions.AUDIT_MANAGE: _ADMIN_ROLES,
    TenantPermissions.TABLE_SQL_READ: _AUDITOR_ROLES,
    TenantPermissions.LIFECYCLE_MANAGE: _ADMIN_ROLES,
    TenantPermissions.FEEDBACK_TRIAGE_WRITE: frozenset(UserRoles.EDIT_ROLES),
}


def allowed_roles_for_permission(permission: str) -> frozenset[str]:
    return _PERMISSION_ROLES.get(str(permission or "").strip(), frozenset())


def all_tenant_permissions() -> tuple[str, ...]:
    return tuple(_PERMISSION_ROLES.keys())


def role_allows(permission: str, *, role: str | None) -> bool:
    role_norm = _normalize_role(role)
    if not role_norm:
        return False
    return role_norm in allowed_roles_for_permission(permission)


def ensure_tenant_permission(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    permission: str,
    *,
    detail: str = "No permission",
) -> TenantMember:
    """
    Ensure `account_id` is a tenant member and has the requested permission.

    Notes:
    - We intentionally reuse DatasetService.ensure_member so dev bootstrap behavior remains unchanged.
    - This helper is for tenant-scoped admin capabilities (settings/observability/audit).
    """
    member = DatasetService.ensure_member(db, tenant_id, account_id)
    role_norm = _normalize_role(getattr(member, "role", None))
    if role_norm not in allowed_roles_for_permission(permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
    return member


__all__ = [
    "TenantPermissions",
    "all_tenant_permissions",
    "allowed_roles_for_permission",
    "ensure_tenant_permission",
    "role_allows",
]
