"""
Tenant-scoped RBAC utilities.

Centralizes role/permission checks so API endpoints avoid ad-hoc role sets.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.constants import UserRoles
from app.models.tenant import TenantMember
from app.services import dataset_service


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


_AUDITOR_ROLES: frozenset[str] = frozenset({UserRoles.OWNER, UserRoles.ADMIN, UserRoles.AUDITOR})

_PERMISSION_ROLES: dict[str, frozenset[str]] = {
    TenantPermissions.SETTINGS_READ: UserRoles.ADMIN_ROLES,
    TenantPermissions.SETTINGS_WRITE: UserRoles.ADMIN_ROLES,
    TenantPermissions.OBSERVABILITY_READ: UserRoles.ADMIN_ROLES,
    TenantPermissions.USAGE_READ: UserRoles.ADMIN_ROLES,
    TenantPermissions.AUDIT_READ: _AUDITOR_ROLES,
    TenantPermissions.AUDIT_MANAGE: UserRoles.ADMIN_ROLES,
    TenantPermissions.TABLE_SQL_READ: _AUDITOR_ROLES,
    TenantPermissions.LIFECYCLE_MANAGE: UserRoles.ADMIN_ROLES,
    TenantPermissions.FEEDBACK_TRIAGE_WRITE: UserRoles.EDIT_ROLES,
}


def allowed_roles_for_permission(permission: str) -> frozenset[str]:
    return _PERMISSION_ROLES.get(permission.strip(), frozenset())


def all_tenant_permissions() -> tuple[str, ...]:
    return tuple(_PERMISSION_ROLES)


def role_allows(permission: str, *, role: str | None) -> bool:
    role_norm = role
    if role_norm:
        role_norm = role_norm.strip().lower()
    return role_norm in allowed_roles_for_permission(permission)


def assert_edit_role(member: TenantMember) -> None:
    role = member.role
    if role:
        role = role.lower()
    if role not in UserRoles.EDIT_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission to edit")


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
    - We intentionally reuse dataset_service.ensure_member so dev bootstrap behavior remains unchanged.
    - This helper is for tenant-scoped admin capabilities (settings/observability/audit).
    """
    member = dataset_service.ensure_member(db, tenant_id, account_id)
    if not role_allows(permission, role=member.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
    return member


__all__ = [
    "TenantPermissions",
    "all_tenant_permissions",
    "allowed_roles_for_permission",
    "assert_edit_role",
    "ensure_tenant_permission",
    "role_allows",
]
