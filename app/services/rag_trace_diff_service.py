"""
PII-safe RAG trace diff helpers.

Purpose:
- Help compare two retrieval runs (typically different retrieval_config_hash / settings)
  using the PII-safe RagTrace shape exposed to the UI.

Design constraints:
- Deterministic, small output (suitable for CI artifacts / debugging).
- Never include raw question/query/chunk snippets.
"""

from collections import Counter
from typing import Any

from app.rag.trace_schema import RagTrace

RAG_TRACE_DIFF_SCHEMA_V1 = "mimirq.rag_trace_diff.v1"


def _delta_float(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return round(b - a, 6)


def _counter_sorted(counter: Counter[str]) -> dict[str, int]:
    # Stable ordering: higher count first, then key.
    items = sorted(counter.items(), key=lambda x: (-x[1], x[0]))
    return {k: v for k, v in items if k}


def _delta_counter(a: Counter[str], b: Counter[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    keys = sorted(set(a.keys()) | set(b.keys()))
    for k in keys:
        d = b[k] - a[k]
        if d:
            out[k] = d
    # Stable ordering: larger magnitude first, then key.
    return dict(sorted(out.items(), key=lambda x: (-abs(x[1]), x[0])))


def diff_rag_traces(a: RagTrace, b: RagTrace) -> dict[str, Any]:
    """
    Compute a compact, deterministic diff summary between two RagTrace objects.

    Output shape is intentionally small and stable (v1).
    """
    ta = a
    tb = b

    hit_a: Counter[str] = Counter()
    hit_b: Counter[str] = Counter()
    role_a: Counter[str] = Counter()
    role_b: Counter[str] = Counter()

    for c in ta.citations:
        ht = c.hit_type.strip() if c.hit_type is not None else None
        rr = c.retrieval_role.strip() if c.retrieval_role is not None else None
        if ht:
            hit_a[ht] += 1
        if rr:
            role_a[rr] += 1

    for c in tb.citations:
        ht = c.hit_type.strip() if c.hit_type is not None else None
        rr = c.retrieval_role.strip() if c.retrieval_role is not None else None
        if ht:
            hit_b[ht] += 1
        if rr:
            role_b[rr] += 1

    out: dict[str, Any] = {
        "schema": RAG_TRACE_DIFF_SCHEMA_V1,
        "request_id_a": ta.request_id,
        "request_id_b": tb.request_id,
        "retrieval_config_hash_a": ta.retrieval.retrieval_config_hash,
        "retrieval_config_hash_b": tb.retrieval.retrieval_config_hash,
        "delta": {
            "citations_count": tb.citations_count - ta.citations_count,
            "retrieval_elapsed_sec": _delta_float(ta.retrieval.elapsed_sec, tb.retrieval.elapsed_sec),
            "rerank_elapsed_sec": _delta_float(ta.rerank.elapsed_sec, tb.rerank.elapsed_sec),
        },
        # Field-level comparisons (stable key set; values may be null).
        "fields": {
            "retrieval.mode": {"a": ta.retrieval.mode, "b": tb.retrieval.mode},
            "retrieval.requested_mode": {"a": ta.retrieval.requested_mode, "b": tb.retrieval.requested_mode},
            "retrieval.auto_routed": {"a": ta.retrieval.auto_routed, "b": tb.retrieval.auto_routed},
            "retrieval.top_k": {"a": ta.retrieval.top_k, "b": tb.retrieval.top_k},
            "retrieval.query_count": {"a": ta.retrieval.query_count, "b": tb.retrieval.query_count},
            "retrieval.query_parallelism": {"a": ta.retrieval.query_parallelism, "b": tb.retrieval.query_parallelism},
            "retrieval.enable_reranker": {"a": ta.retrieval.enable_reranker, "b": tb.retrieval.enable_reranker},
            "retrieval.reranker_provider": {"a": ta.retrieval.reranker_provider, "b": tb.retrieval.reranker_provider},
            "retrieval.reranker_top_n": {"a": ta.retrieval.reranker_top_n, "b": tb.retrieval.reranker_top_n},
            "rerank.enabled": {"a": ta.rerank.enabled, "b": tb.rerank.enabled},
            "rerank.provider": {"a": ta.rerank.provider, "b": tb.rerank.provider},
            "rerank.top_n": {"a": ta.rerank.top_n, "b": tb.rerank.top_n},
            "rerank.model_used": {"a": ta.rerank.model_used, "b": tb.rerank.model_used},
        },
        "hit_type_counts": {
            "a": _counter_sorted(hit_a),
            "b": _counter_sorted(hit_b),
            "delta": _delta_counter(hit_a, hit_b),
        },
        "retrieval_role_counts": {
            "a": _counter_sorted(role_a),
            "b": _counter_sorted(role_b),
            "delta": _delta_counter(role_a, role_b),
        },
    }

    return out


__all__ = ["RAG_TRACE_DIFF_SCHEMA_V1", "diff_rag_traces"]
