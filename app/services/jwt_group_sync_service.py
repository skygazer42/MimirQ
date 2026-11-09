"""
JWT group claim sync (enterprise).

Opt-in best-effort service to upsert tenant groups + memberships from a verified JWT payload.

Security/PII notes:
- Never log raw group lists (names/ids) in public logs.
- Keep all actions tenant-scoped.
"""

import threading
import time
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.tenant_group import TenantGroup, TenantGroupMember
from app.rag.core.logging import get_logger

logger = get_logger("services.jwt_group_sync")

# In-process TTL throttle cache (best-effort; per worker process).
_sync_lock = threading.Lock()
_last_sync_ts: dict[tuple[str, str], float] = {}


def _nested_get(payload: dict[str, Any], path: str) -> Any:
    """
    Best-effort support for dotted claim paths (e.g. "realm_access.roles").
    """
    if not path:
        return None
    cur: Any = payload
    for part in path.split("."):
        if not part:
            continue
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def parse_group_names_from_jwt_payload(payload: dict[str, Any], *, claim: str, max_groups: int) -> list[str]:
    """
    Parse group names from a JWT payload claim.

    - Trims and de-dupes
    - Skips empty/oversized items
    - Caps list size
    """
    if max_groups <= 0:
        return []

    raw = _nested_get(payload, claim)
    if raw is None:
        return []

    items: list[Any]
    if isinstance(raw, (list, tuple, set)):
        items = list(raw)
    else:
        items = [raw]

    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        name = str(item or "").strip()
        if not name or name in seen:
            continue
        if len(name) > 255:
            continue
        seen.add(name)
        out.append(name)
        if len(out) >= max_groups:
            break
    return out


def _should_sync(*, tenant_id: UUID, account_id: str, ttl_sec: float) -> bool:
    """
    Best-effort in-process TTL throttle.

    Note: key is stringified to avoid UUID hash/version edge cases across reloads.
    """
    if ttl_sec <= 0:
        return True

    now = time.monotonic()
    key = (str(tenant_id), account_id)
    with _sync_lock:
        last = _last_sync_ts.get(key)
        if last is not None and (now - last) < ttl_sec:
            return False
        _last_sync_ts[key] = now
        return True


def maybe_sync_jwt_groups(*, tenant_id: UUID, account_id: str, jwt_payload: dict[str, Any]) -> None:
    """
    Throttled wrapper. Safe to call on every request.
    """
    if not settings.JWT_GROUPS_SYNC_ENABLED:
        return
    ttl = float(settings.JWT_GROUPS_SYNC_TTL_SEC)
    if not _should_sync(tenant_id=tenant_id, account_id=account_id, ttl_sec=ttl):
        return
    try:
        sync_jwt_groups_best_effort(tenant_id=tenant_id, account_id=account_id, jwt_payload=jwt_payload)
    except Exception as exc:  # noqa: BLE001
        # Never block auth; keep logs PII-minimal (no group list).
        logger.warning(
            "JWT group sync failed: tenant_id=%s error_type=%s",
            tenant_id,
            type(exc).__name__,
        )


def sync_jwt_groups_best_effort(*, tenant_id: UUID, account_id: str, jwt_payload: dict[str, Any]) -> None:
    """
    Best-effort, idempotent upsert of:
    - tenant_groups (by name)
    - tenant_group_members (by tenant_id + group_id + user_id)
    """
    claim = (settings.JWT_GROUPS_CLAIM or "groups").strip()
    max_groups = max(0, min(settings.JWT_GROUPS_MAX_GROUPS, 2000))

    group_names = parse_group_names_from_jwt_payload(jwt_payload, claim=claim, max_groups=max_groups)
    if not group_names:
        return

    db = SessionLocal()
    try:
        # 1) Ensure groups exist (upsert by name, tenant-scoped).
        existing = (
            db.query(TenantGroup)
            .filter(
                TenantGroup.tenant_id == tenant_id,
                TenantGroup.name.in_(group_names),
            )
            .all()
        )
        existing_names = {group.name for group in existing}
        to_create: list[TenantGroup] = []
        for name in group_names:
            if name in existing_names:
                continue
            to_create.append(TenantGroup(tenant_id=tenant_id, name=name))
        if to_create:
            db.add_all(to_create)
            db.flush()

        group_ids = {group.id for group in existing + to_create}

        # 2) Ensure memberships exist (add-only; no removals in this wave).
        uid = account_id
        rows = (
            db.query(TenantGroupMember.group_id)
            .filter(
                TenantGroupMember.tenant_id == tenant_id,
                TenantGroupMember.user_id == uid,
                TenantGroupMember.group_id.in_(list(group_ids)),
            )
            .all()
        )
        existing_member_gids = {row[0] for row in rows}
        to_add_gids = [gid for gid in group_ids if gid not in existing_member_gids]
        if to_add_gids:
            db.add_all(
                [
                    TenantGroupMember(
                        tenant_id=tenant_id,
                        group_id=gid,
                        user_id=uid,
                    )
                    for gid in to_add_gids
                ]
            )

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


__all__ = ["parse_group_names_from_jwt_payload", "maybe_sync_jwt_groups", "sync_jwt_groups_best_effort"]
