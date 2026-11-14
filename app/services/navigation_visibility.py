"""Navigation visibility policy shared by settings and RBAC surfaces."""

from collections.abc import Iterable, Iterator

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


def _iter_raw_modules(value: object) -> Iterator[str]:
    if value is None:
        return
    if isinstance(value, str):
        source: Iterable[object] = value.replace(";", ",").split(",")
    elif isinstance(value, Iterable):
        source = value
    else:
        source = (value,)
    for part in source:
        if part is not None:
            yield str(part).strip()


def normalize_navigation_modules(value: object, *, reject_unknown: bool = False) -> list[str]:
    """Normalize a user-visible module list while preserving product order."""
    requested = {part for part in _iter_raw_modules(value) if part}
    unknown = sorted(requested.difference(_ALLOWED_NAVIGATION_MODULE_SET))
    if reject_unknown and unknown:
        raise ValueError(f"Unknown navigation module(s): {', '.join(unknown)}")

    return [module for module in ADMIN_CONTROLLED_NAVIGATION_MODULES if module in requested]
