"""Navigation visibility policy shared by settings and RBAC surfaces."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

ADMIN_CONTROLLED_NAVIGATION_MODULES: tuple[str, ...] = (
    "governanceProfiles",
    "commonLines",
    "knowledgeGraph",
    "graphSnapshots",
    "graphDiagnostics",
    "ragas",
    "ablations",
    "reports",
    "prompts",
)

_ALLOWED_NAVIGATION_MODULE_SET = frozenset(ADMIN_CONTROLLED_NAVIGATION_MODULES)


def _iter_raw_modules(value: Any) -> Iterable[str]:
    if value is None:
        return
    if isinstance(value, str):
        source: Iterable[Any] = value.replace(";", ",").split(",")
    elif isinstance(value, Iterable):
        source = value
    else:
        source = (value,)
    for part in source:
        yield str(part or "").strip()


def normalize_navigation_modules(value: Any, *, reject_unknown: bool = False) -> list[str]:
    """Normalize a user-visible module list while preserving product order."""
    requested = {part for part in _iter_raw_modules(value) if part}
    unknown = sorted(requested.difference(_ALLOWED_NAVIGATION_MODULE_SET))
    if reject_unknown and unknown:
        raise ValueError(f"Unknown navigation module(s): {', '.join(unknown)}")

    return [module for module in ADMIN_CONTROLLED_NAVIGATION_MODULES if module in requested]


def serialize_navigation_modules(value: Any) -> str:
    return ",".join(normalize_navigation_modules(value, reject_unknown=True))


def navigation_user_visible_modules_from_settings(settings_obj: Any) -> list[str]:
    return normalize_navigation_modules(getattr(settings_obj, "NAVIGATION_USER_VISIBLE_MODULES", "") or "")
