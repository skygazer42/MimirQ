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
    if not enabled:
        return "all"
    if value is None:
        return "none"
    return value.strip() or "none"


def _labels(*, tenant_id: str | None, dataset_id: str | None) -> dict[str, str]:
    return {
        "tenant_id": _label_value(
            enabled=settings.PROMETHEUS_RAG_LABEL_TENANT_ID,
            value=tenant_id,
        ),
        "dataset_id": _label_value(
            enabled=settings.PROMETHEUS_RAG_LABEL_DATASET_ID,
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
    if not settings.PROMETHEUS_ENABLED:
        return

    labels = _labels(tenant_id=tenant_id, dataset_id=dataset_id)

    count = max(0, citations_count)
    RAG_CITATIONS_COUNT.labels(**labels).observe(float(count))
    if count == 0:
        RAG_ZERO_HIT_TOTAL.labels(**labels).inc()

    if retrieval_elapsed_sec >= 0:
        RAG_RETRIEVAL_ELAPSED_SECONDS.labels(**labels).observe(retrieval_elapsed_sec)

    if rerank_elapsed_sec is not None:
        if rerank_elapsed_sec >= 0:
            RAG_RERANK_ELAPSED_SECONDS.labels(**labels).observe(rerank_elapsed_sec)

    if has_error:
        RAG_ERRORS_TOTAL.labels(**labels).inc()


__all__ = ["observe_rag_sli"]
