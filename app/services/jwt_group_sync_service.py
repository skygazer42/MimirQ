"""
JWT group claim sync (enterprise).

Opt-in best-effort service to upsert tenant groups + memberships from a verified JWT payload.

Security/PII notes:
- Never log raw group lists (names/ids) in public logs.
- Keep all actions tenant-scoped.
"""

from __future__ import annotations

import contextlib
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
    for part in str(path).split("."):
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
    max_items = int(max_groups or 0)
    if max_items <= 0:
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
        if len(out) >= max_items:
            break
    return out


def _should_sync(*, tenant_id: UUID, account_id: str, ttl_sec: float) -> bool:
    """
    Best-effort in-process TTL throttle.

    Note: key is stringified to avoid UUID hash/version edge cases across reloads.
    """
    ttl = float(ttl_sec or 0)
    if ttl <= 0:
        return True

    uid = str(account_id or "").strip()
    if not uid:
        return False

    now = time.monotonic()
    key = (str(tenant_id), uid)
    with _sync_lock:
        last = _last_sync_ts.get(key)
        if last is not None and (now - last) < ttl:
            return False
        _last_sync_ts[key] = now
        return True


def maybe_sync_jwt_groups(*, tenant_id: UUID, account_id: str, jwt_payload: dict[str, Any]) -> None:
    """
    Throttled wrapper. Safe to call on every request.
    """
    if not bool(getattr(settings, "JWT_GROUPS_SYNC_ENABLED", False)):
        return
    ttl = float(getattr(settings, "JWT_GROUPS_SYNC_TTL_SEC", 60) or 60)
    if not _should_sync(tenant_id=tenant_id, account_id=account_id, ttl_sec=ttl):
        return
    try:
        sync_jwt_groups_best_effort(tenant_id=tenant_id, account_id=account_id, jwt_payload=jwt_payload)
    except Exception as exc:  # noqa: BLE001
        # Never block auth; keep logs PII-minimal (no group list).
        logger.debug("JWT group sync failed (%s)", exc.__class__.__name__)


def sync_jwt_groups_best_effort(*, tenant_id: UUID, account_id: str, jwt_payload: dict[str, Any]) -> None:
    """
    Best-effort, idempotent upsert of:
    - tenant_groups (by name)
    - tenant_group_members (by tenant_id + group_id + user_id)
    """
    claim = str(getattr(settings, "JWT_GROUPS_CLAIM", "") or "groups").strip()
    max_groups = int(getattr(settings, "JWT_GROUPS_MAX_GROUPS", 200) or 200)
    max_groups = max(0, min(max_groups, 2000))

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
        existing_by_name = {str(getattr(g, "name", "") or ""): g for g in existing}
        to_create: list[TenantGroup] = []
        for name in group_names:
            if name in existing_by_name:
                continue
            to_create.append(TenantGroup(tenant_id=tenant_id, name=name))
        if to_create:
            db.add_all(to_create)
            db.flush()

        all_groups = list(existing) + list(to_create)
        group_ids = {g.id for g in all_groups if getattr(g, "id", None) is not None}
        if not group_ids:
            db.commit()
            return

        # 2) Ensure memberships exist (add-only; no removals in this wave).
        uid = str(account_id or "").strip()
        rows = (
            db.query(TenantGroupMember.group_id)
            .filter(
                TenantGroupMember.tenant_id == tenant_id,
                TenantGroupMember.user_id == uid,
                TenantGroupMember.group_id.in_(list(group_ids)),
            )
            .all()
        )
        existing_member_gids = {row[0] for row in rows if row and row[0]}
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
        with contextlib.suppress(Exception):
            db.rollback()
        raise
    finally:
        db.close()


__all__ = ["parse_group_names_from_jwt_payload", "maybe_sync_jwt_groups", "sync_jwt_groups_best_effort"]
