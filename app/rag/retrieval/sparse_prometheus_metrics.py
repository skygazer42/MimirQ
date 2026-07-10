"""
Prometheus metrics for sparse retrieval (SPLADE-style channel).

Design goals:
- PII-safe: never label by query, tenant/dataset ids, document ids, or text hashes.
- Low-cardinality labels: provider + small bounded outcomes only.
- Optional: enabled only when PROMETHEUS_ENABLED=true.
"""


import re

from prometheus_client import Counter, Histogram

from app.core.config import settings

_PROVIDERS = {"deterministic", "splade", "unknown"}
_OUTCOMES = {"ok", "empty", "error", "skipped"}
_SEARCH_REASONS = {
    "none",
    "sparse_disabled",
    "provider_invalid",
    "splade_model_missing",
    "scope_empty",
    "no_candidates",
    "index_load_error",
    "index_build_failed",
    "exception",
    "unknown",
}
_INDEX_LOAD_OUTCOMES = {"hit", "miss", "error", "skipped"}
_INDEX_SAVE_OUTCOMES = {"ok", "error", "skipped"}
_BUILD_KINDS = {"full", "incremental"}


SPARSE_SEARCH_TOTAL = Counter(
    "rag_sparse_search_total",
    "Total sparse retrieval searches (per-query, per-process; best-effort)",
    ["provider", "outcome"],
)
SPARSE_SEARCH_DURATION_SECONDS = Histogram(
    "rag_sparse_search_duration_seconds",
    "Sparse retrieval search duration in seconds (per query; best-effort)",
    ["provider", "outcome"],
    buckets=(0.001, 0.002, 0.005, 0.01, 0.02, 0.04, 0.08, 0.15, 0.3, 0.6, 1.0, 2.0, 4.0, 8.0),
)
SPARSE_SEARCH_CANDIDATES_COUNT = Histogram(
    "rag_sparse_search_candidates_count",
    "Sparse retrieval candidates count (per query; best-effort)",
    ["provider", "outcome"],
    buckets=(0, 1, 2, 3, 5, 10, 20, 50, 80, 100, 200, 500),
)
SPARSE_SEARCH_REASON_TOTAL = Counter(
    "rag_sparse_search_reason_total",
    "Sparse retrieval fallback/skip reason counts (low-cardinality; best-effort)",
    ["provider", "reason"],
)

SPARSE_INDEX_LOAD_TOTAL = Counter(
    "rag_sparse_index_load_total",
    "Total sparse index load attempts from disk (best-effort)",
    ["provider", "outcome"],
)
SPARSE_INDEX_SAVE_TOTAL = Counter(
    "rag_sparse_index_save_total",
    "Total sparse index save attempts to disk (best-effort)",
    ["provider", "outcome"],
)
SPARSE_INDEX_BUILD_DURATION_SECONDS = Histogram(
    "rag_sparse_index_build_duration_seconds",
    "Sparse index build duration in seconds (best-effort)",
    ["provider", "kind", "outcome"],
    buckets=(0.005, 0.01, 0.02, 0.04, 0.08, 0.15, 0.3, 0.6, 1.0, 2.0, 4.0, 8.0, 15.0, 30.0),
)


def _enabled() -> bool:
    return bool(getattr(settings, "PROMETHEUS_ENABLED", False))


def _norm_provider(value: str | None) -> str:
    s = str(value or "").strip().lower()
    s = re.sub(r"[^a-z0-9._:-]+", "_", s)
    s = (s[:40] or "").strip("_")
    if not s:
        return "unknown"
    if s in {"det", "deterministic"}:
        return "deterministic"
    if s in {"splade"}:
        return "splade"
    return "unknown"


def _norm_outcome(value: str | None, *, allowed: set[str], fallback: str) -> str:
    s = str(value or "").strip().lower()
    s = re.sub(r"[^a-z0-9._:-]+", "_", s)
    s = (s[:24] or "").strip("_")
    if not s:
        return fallback
    if s not in allowed:
        return fallback
    return s


def observe_sparse_search(
    *,
    provider: str | None,
    outcome: str,
    duration_sec: float | None,
    candidates_count: int | None,
    reason: str | None = None,
) -> None:
    if not _enabled():
        return

    p = _norm_provider(provider)
    oc = _norm_outcome(outcome, allowed=_OUTCOMES, fallback="error")
    SPARSE_SEARCH_TOTAL.labels(provider=p, outcome=oc).inc()
    rs = _norm_outcome(reason, allowed=_SEARCH_REASONS, fallback="unknown")
    SPARSE_SEARCH_REASON_TOTAL.labels(provider=p, reason=rs).inc()

    try:
        sec = float(duration_sec) if duration_sec is not None else None
    except Exception:
        sec = None
    if sec is not None and sec >= 0.0:
        SPARSE_SEARCH_DURATION_SECONDS.labels(provider=p, outcome=oc).observe(sec)

    try:
        cc = int(candidates_count) if candidates_count is not None else None
    except Exception:
        cc = None
    if cc is not None and cc >= 0:
        SPARSE_SEARCH_CANDIDATES_COUNT.labels(provider=p, outcome=oc).observe(float(cc))


def observe_sparse_index_load(*, provider: str | None, outcome: str) -> None:
    if not _enabled():
        return
    p = _norm_provider(provider)
    oc = _norm_outcome(outcome, allowed=_INDEX_LOAD_OUTCOMES, fallback="error")
    SPARSE_INDEX_LOAD_TOTAL.labels(provider=p, outcome=oc).inc()


def observe_sparse_index_save(*, provider: str | None, outcome: str) -> None:
    if not _enabled():
        return
    p = _norm_provider(provider)
    oc = _norm_outcome(outcome, allowed=_INDEX_SAVE_OUTCOMES, fallback="error")
    SPARSE_INDEX_SAVE_TOTAL.labels(provider=p, outcome=oc).inc()


def observe_sparse_index_build(
    *,
    provider: str | None,
    kind: str,
    outcome: str,
    duration_sec: float | None,
) -> None:
    if not _enabled():
        return
    p = _norm_provider(provider)
    kd = _norm_outcome(kind, allowed=_BUILD_KINDS, fallback="full")
    oc = _norm_outcome(outcome, allowed=_OUTCOMES, fallback="error")

    try:
        sec = float(duration_sec) if duration_sec is not None else None
    except Exception:
        sec = None
    if sec is None or sec < 0.0:
        return
    SPARSE_INDEX_BUILD_DURATION_SECONDS.labels(provider=p, kind=kd, outcome=oc).observe(sec)


__all__ = [
    "SPARSE_SEARCH_TOTAL",
    "SPARSE_SEARCH_DURATION_SECONDS",
    "SPARSE_SEARCH_CANDIDATES_COUNT",
    "SPARSE_SEARCH_REASON_TOTAL",
    "SPARSE_INDEX_LOAD_TOTAL",
    "SPARSE_INDEX_SAVE_TOTAL",
    "SPARSE_INDEX_BUILD_DURATION_SECONDS",
    "observe_sparse_search",
    "observe_sparse_index_load",
    "observe_sparse_index_save",
    "observe_sparse_index_build",
]
