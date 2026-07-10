"""
Prometheus metrics for Milvus vector store compatibility fallbacks.

Design goals:
- PII-safe: never label by tenant/dataset/query ids or raw expr strings.
- Low-cardinality labels: boolean flags and a small fixed set of "dropped_fields".
- Optional: enabled only when PROMETHEUS_ENABLED=true.
"""


import re

from prometheus_client import Counter

from app.core.config import settings

MILVUS_WRITE_COMPAT_FALLBACK_TOTAL = Counter(
    "vector_milvus_write_compat_fallback_total",
    "Total Milvus write compatibility fallbacks (retry after dropping scalar fields)",
    ["dropped_fields"],
)
MILVUS_SEARCH_EXPR_FALLBACK_TOTAL = Counter(
    "vector_milvus_search_expr_fallback_total",
    "Total Milvus search expr fallbacks (retry without metadata expr pushdown)",
    ["has_metadata_expr", "has_base_expr"],
)


def _enabled() -> bool:
    return bool(getattr(settings, "PROMETHEUS_ENABLED", False))


_SAFE_LABEL_RE = re.compile(r"[^a-z0-9._:-]+")


def _safe_label(value: str | None, *, fallback: str) -> str:
    s = str(value or "").strip().lower()
    s = _SAFE_LABEL_RE.sub("_", s)
    s = (s[:64] or "").strip("_")
    return s or fallback


def observe_milvus_write_compat_fallback(*, dropped_fields: str) -> None:
    if not _enabled():
        return
    dropped = _safe_label(dropped_fields, fallback="unknown")
    MILVUS_WRITE_COMPAT_FALLBACK_TOTAL.labels(dropped_fields=dropped).inc()


def observe_milvus_search_expr_fallback(*, has_metadata_expr: bool, has_base_expr: bool) -> None:
    if not _enabled():
        return
    MILVUS_SEARCH_EXPR_FALLBACK_TOTAL.labels(
        has_metadata_expr=str(bool(has_metadata_expr)).lower(),
        has_base_expr=str(bool(has_base_expr)).lower(),
    ).inc()


__all__ = [
    "observe_milvus_write_compat_fallback",
    "observe_milvus_search_expr_fallback",
]

