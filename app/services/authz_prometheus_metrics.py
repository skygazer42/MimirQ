"""
Prometheus metrics for authorization (ACL) checks.

Design goals:
- Tenant-safe/PII-safe: never label by tenant/account/group ids.
- Low-cardinality: labels are bounded (resource/action/result).
- Optional: enabled only when PROMETHEUS_ENABLED=true.
"""


from prometheus_client import Counter

from app.core.config import settings

_RESOURCES = {"dataset", "document"}
_ACTIONS = {"read", "write"}
_RESULTS = {"allow", "deny_no_groups", "deny_no_match", "unknown"}

AUTHZ_GROUP_PERMISSION_TOTAL = Counter(
    "authz_group_permission_total",
    "Total group-based permission checks (allow/deny) for datasets/documents",
    ["resource", "action", "result"],
)


def _enabled() -> bool:
    return bool(getattr(settings, "PROMETHEUS_ENABLED", False))


def _norm(value: str | None, *, allowed: set[str], fallback: str = "unknown") -> str:
    v = (str(value or "")).strip().lower()
    if not v:
        return fallback
    if v not in allowed:
        return fallback
    return v


def observe_group_permission_check(*, resource: str, action: str, result: str) -> None:
    """
    Record a group-based permission decision.

    Labels:
    - resource: dataset|document
    - action: read|write
    - result: allow|deny_no_groups|deny_no_match|unknown
    """
    if not _enabled():
        return

    AUTHZ_GROUP_PERMISSION_TOTAL.labels(
        resource=_norm(resource, allowed=_RESOURCES),
        action=_norm(action, allowed=_ACTIONS),
        result=_norm(result, allowed=_RESULTS),
    ).inc()


__all__ = ["AUTHZ_GROUP_PERMISSION_TOTAL", "observe_group_permission_check"]
