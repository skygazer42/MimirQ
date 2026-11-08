"""Synchronize optional directory memberships after JWT authentication."""

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("services.jwt_membership_sync")


def sync_jwt_memberships(
    *,
    tenant_id,
    user_id,
    payload,
    request_id,
    ip,
    user_agent,
):
    """Run directory syncs independently; each service owns its transactions.

    These opt-in sync failures do not reject an already verified identity.
    Route-level membership and permission checks still authorize access.
    """
    if settings.JWT_GROUPS_SYNC_ENABLED:
        try:
            from app.services.jwt_group_sync_service import maybe_sync_jwt_groups

            maybe_sync_jwt_groups(tenant_id=tenant_id, account_id=user_id, jwt_payload=payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("JWT group sync failed during auth; continuing without sync: %s", exc)

    if settings.JWT_TENANT_MEMBER_AUTO_PROVISION_ENABLED:
        try:
            from app.core.database import SessionLocal
            from app.services.tenant_member_provisioning_service import (
                maybe_auto_provision_jwt_tenant_member_best_effort,
            )

            maybe_auto_provision_jwt_tenant_member_best_effort(
                db_factory=SessionLocal,
                tenant_id=tenant_id,
                user_id=user_id,
                request_id=request_id,
                ip=ip,
                user_agent=user_agent,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("JWT tenant member auto-provisioning failed during auth; continuing: %s", exc)
