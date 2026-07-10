"""
Prometheus metrics for retrieval-only (Evidence API).

Keep labels low-cardinality:
- Do not label by tenant/dataset/query.
"""


from prometheus_client import Counter, Histogram

from app.core.config import settings

EVIDENCE_RETRIEVE_TOTAL = Counter(
    "rag_evidence_retrieve_total",
    "Total Evidence API retrieval requests (retrieval-only)",
    ["has_evidence", "abstain_triggered", "retrieval_mode", "selected_pass"],
)
EVIDENCE_RETRIEVE_DURATION_SECONDS = Histogram(
    "rag_evidence_retrieve_duration_seconds",
    "Evidence API end-to-end duration in seconds",
    ["retrieval_mode", "selected_pass"],
)
EVIDENCE_RETRIEVE_CITATIONS_COUNT = Histogram(
    "rag_evidence_retrieve_citations_count",
    "Evidence API citations count",
    ["retrieval_mode", "selected_pass"],
    buckets=(0, 1, 2, 3, 5, 10, 20, 50, 80, 100),
)
EVIDENCE_RETRIEVE_TOP_SCORE = Histogram(
    "rag_evidence_retrieve_top_score",
    "Evidence API top relevance score",
    ["retrieval_mode", "selected_pass"],
    buckets=(0.0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)


def observe_evidence_retrieve(
    *,
    duration_sec: float,
    has_evidence: bool,
    abstain_triggered: bool,
    retrieval_mode: str,
    selected_pass: str,
    citations_count: int,
    top_relevance_score: float,
) -> None:
    if not bool(getattr(settings, "PROMETHEUS_ENABLED", False)):
        return

    mode = (retrieval_mode or "").strip().lower() or "unknown"
    sel = (selected_pass or "").strip().lower() or "primary"
    EVIDENCE_RETRIEVE_TOTAL.labels(
        has_evidence=str(bool(has_evidence)).lower(),
        abstain_triggered=str(bool(abstain_triggered)).lower(),
        retrieval_mode=mode,
        selected_pass=sel,
    ).inc()
    EVIDENCE_RETRIEVE_DURATION_SECONDS.labels(retrieval_mode=mode, selected_pass=sel).observe(max(0.0, float(duration_sec or 0.0)))
    EVIDENCE_RETRIEVE_CITATIONS_COUNT.labels(retrieval_mode=mode, selected_pass=sel).observe(max(0.0, float(citations_count or 0.0)))
    EVIDENCE_RETRIEVE_TOP_SCORE.labels(retrieval_mode=mode, selected_pass=sel).observe(max(0.0, min(1.0, float(top_relevance_score or 0.0))))


__all__ = ["observe_evidence_retrieve"]
