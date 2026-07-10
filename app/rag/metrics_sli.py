"""
Prometheus SLI metrics for the full RAG (chat) path.

Design goals:
- PII-safe: never label by query text/hash/document ids.
- Low-cardinality by default: tenant_id/dataset_id labels can be enabled explicitly,
  otherwise values are collapsed to "all".
"""


from prometheus_client import Counter, Histogram

from app.core.config import settings

_RAG_LABEL_NAMES = ["tenant_id", "dataset_id"]


def _label_value(*, enabled: bool, value: str | None) -> str:
    if not bool(enabled):
        return "all"
    v = str(value or "").strip()
    return v or "none"


def _labels(*, tenant_id: str | None, dataset_id: str | None) -> dict[str, str]:
    return {
        "tenant_id": _label_value(
            enabled=bool(getattr(settings, "PROMETHEUS_RAG_LABEL_TENANT_ID", False)),
            value=tenant_id,
        ),
        "dataset_id": _label_value(
            enabled=bool(getattr(settings, "PROMETHEUS_RAG_LABEL_DATASET_ID", False)),
            value=dataset_id,
        ),
    }


RAG_ZERO_HIT_TOTAL = Counter(
    "rag_zero_hit_total",
    "Total RAG requests with zero citations (citations_count=0)",
    _RAG_LABEL_NAMES,
)
RAG_ERRORS_TOTAL = Counter(
    "rag_errors_total",
    "Total RAG requests with retrieval errors (per-request, not per-error)",
    _RAG_LABEL_NAMES,
)
RAG_CITATIONS_COUNT = Histogram(
    "rag_citations_count",
    "RAG citations count (per request)",
    _RAG_LABEL_NAMES,
    buckets=(0, 1, 2, 3, 5, 10, 20, 50, 80, 100),
)
RAG_RETRIEVAL_ELAPSED_SECONDS = Histogram(
    "rag_retrieval_elapsed_seconds",
    "RAG retrieval elapsed seconds (per request)",
    _RAG_LABEL_NAMES,
    buckets=(0.05, 0.1, 0.2, 0.4, 0.8, 1.5, 2.5, 4, 6, 9, 13, 20, 30),
)
RAG_RERANK_ELAPSED_SECONDS = Histogram(
    "rag_rerank_elapsed_seconds",
    "RAG rerank elapsed seconds (per request; observed only when available)",
    _RAG_LABEL_NAMES,
    buckets=(0.01, 0.02, 0.05, 0.1, 0.2, 0.4, 0.8, 1.5, 2.5, 4, 6, 9, 13, 20),
)


def observe_rag_sli(
    *,
    tenant_id: str | None,
    dataset_id: str | None,
    citations_count: int,
    retrieval_elapsed_sec: float,
    rerank_elapsed_sec: float | None,
    has_error: bool,
) -> None:
    if not bool(getattr(settings, "PROMETHEUS_ENABLED", False)):
        return

    labels = _labels(tenant_id=tenant_id, dataset_id=dataset_id)

    cc = max(0, int(citations_count or 0))
    RAG_CITATIONS_COUNT.labels(**labels).observe(float(cc))
    if cc == 0:
        RAG_ZERO_HIT_TOTAL.labels(**labels).inc()

    elapsed = float(retrieval_elapsed_sec or 0.0)
    if elapsed >= 0:
        RAG_RETRIEVAL_ELAPSED_SECONDS.labels(**labels).observe(elapsed)

    if rerank_elapsed_sec is not None:
        rr = float(rerank_elapsed_sec or 0.0)
        if rr >= 0:
            RAG_RERANK_ELAPSED_SECONDS.labels(**labels).observe(rr)

    if bool(has_error):
        RAG_ERRORS_TOTAL.labels(**labels).inc()


__all__ = ["observe_rag_sli"]

