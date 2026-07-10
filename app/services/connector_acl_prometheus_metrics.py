"""
Prometheus metrics for connector ACL application (best-effort, PII-safe).

Design goals:
- Tenant-safe / PII-safe: never label by tenant/account/group/document ids.
- Low-cardinality: labels are bounded (connector_id, mode, shape).
- Optional: enabled only when PROMETHEUS_ENABLED=true.
"""


import re

from prometheus_client import Counter

from app.core.config import settings

_MODES = {"inherit", "only_me", "all_team_members", "partial_members", "unknown"}
_SHAPES = {
    "inherit",
    "only_me",
    "all_team_members",
    "partial_empty",
    "members_only",
    "groups_only",
    "members_and_groups",
    "unknown_mode",
}

CONNECTOR_ACL_APPLY_TOTAL = Counter(
    "connector_acl_apply_total",
    "Total connector document ACL applications",
    ["connector_id", "mode", "shape"],
)

CONNECTOR_ACL_APPLY_ERRORS_TOTAL = Counter(
    "connector_acl_apply_errors_total",
    "Total connector document ACL application errors",
    ["connector_id", "mode"],
)


def _enabled() -> bool:
    return bool(getattr(settings, "PROMETHEUS_ENABLED", False))


def _norm_connector_id(value: str | None) -> str:
    s = str(value or "").strip().lower()
    s = re.sub(r"[^a-z0-9._:-]+", "_", s)
    return (s[:80] or "unknown").strip("_") or "unknown"


def _norm_mode(value: str | None) -> str:
    s = str(value or "").strip().lower()
    if not s:
        return "inherit"
    if s in {"", "inherit", "null", "none"}:
        return "inherit"
    if s in {"only_me", "all_team_members", "partial_members"}:
        return s
    return "unknown"


def _shape(*, mode: str, member_count: int, group_count: int) -> str:
    if mode == "inherit":
        return "inherit"
    if mode == "only_me":
        return "only_me"
    if mode == "all_team_members":
        return "all_team_members"
    if mode == "partial_members":
        m = max(0, int(member_count or 0))
        g = max(0, int(group_count or 0))
        if m > 0 and g > 0:
            return "members_and_groups"
        if m > 0:
            return "members_only"
        if g > 0:
            return "groups_only"
        return "partial_empty"
    return "unknown_mode"


def observe_connector_acl_apply(
    *,
    connector_id: str | None,
    mode: str | None,
    member_count: int = 0,
    group_count: int = 0,
) -> None:
    if not _enabled():
        return
    cid = _norm_connector_id(connector_id)
    m = _norm_mode(mode)
    sh = _shape(mode=m, member_count=member_count, group_count=group_count)
    if m not in _MODES:
        m = "unknown"
    if sh not in _SHAPES:
        sh = "unknown_mode"
    CONNECTOR_ACL_APPLY_TOTAL.labels(connector_id=cid, mode=m, shape=sh).inc()


def observe_connector_acl_apply_error(*, connector_id: str | None, mode: str | None) -> None:
    if not _enabled():
        return
    cid = _norm_connector_id(connector_id)
    m = _norm_mode(mode)
    if m not in _MODES:
        m = "unknown"
    CONNECTOR_ACL_APPLY_ERRORS_TOTAL.labels(connector_id=cid, mode=m).inc()


__all__ = [
    "CONNECTOR_ACL_APPLY_TOTAL",
    "CONNECTOR_ACL_APPLY_ERRORS_TOTAL",
    "observe_connector_acl_apply",
    "observe_connector_acl_apply_error",
]

