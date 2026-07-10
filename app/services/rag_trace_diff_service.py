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


def _to_int(v: Any) -> int:
    try:
        return int(v) if v is not None else 0
    except Exception:
        return 0


def _to_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _delta_float(a: Any, b: Any) -> float | None:
    fa = _to_float(a)
    fb = _to_float(b)
    if fa is None or fb is None:
        return None
    return round(float(fb - fa), 6)


def _counter_sorted(counter: Counter[str]) -> dict[str, int]:
    # Stable ordering: higher count first, then key.
    items = sorted(counter.items(), key=lambda x: (-int(x[1] or 0), str(x[0] or "")))
    return {str(k): int(v) for k, v in items if k}


def _delta_counter(a: Counter[str], b: Counter[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    keys = sorted(set(a.keys()) | set(b.keys()))
    for k in keys:
        d = int(b.get(k, 0) or 0) - int(a.get(k, 0) or 0)
        if d:
            out[str(k)] = int(d)
    # Stable ordering: larger magnitude first, then key.
    return dict(sorted(out.items(), key=lambda x: (-abs(int(x[1] or 0)), str(x[0] or ""))))


def diff_rag_traces(a: RagTrace, b: RagTrace) -> dict[str, Any]:
    """
    Compute a compact, deterministic diff summary between two RagTrace objects.

    Output shape is intentionally small and stable (v1).
    """
    ta = a or RagTrace()
    tb = b or RagTrace()

    hit_a: Counter[str] = Counter()
    hit_b: Counter[str] = Counter()
    role_a: Counter[str] = Counter()
    role_b: Counter[str] = Counter()

    for c in (ta.citations or []):
        ht = str(getattr(c, "hit_type", None) or "").strip() or ""
        rr = str(getattr(c, "retrieval_role", None) or "").strip() or ""
        if ht:
            hit_a[ht] += 1
        if rr:
            role_a[rr] += 1

    for c in (tb.citations or []):
        ht = str(getattr(c, "hit_type", None) or "").strip() or ""
        rr = str(getattr(c, "retrieval_role", None) or "").strip() or ""
        if ht:
            hit_b[ht] += 1
        if rr:
            role_b[rr] += 1

    out: dict[str, Any] = {
        "schema": RAG_TRACE_DIFF_SCHEMA_V1,
        "request_id_a": ta.request_id,
        "request_id_b": tb.request_id,
        "retrieval_config_hash_a": getattr(getattr(ta, "retrieval", None), "retrieval_config_hash", None),
        "retrieval_config_hash_b": getattr(getattr(tb, "retrieval", None), "retrieval_config_hash", None),
        "delta": {
            "citations_count": _to_int(tb.citations_count) - _to_int(ta.citations_count),
            "retrieval_elapsed_sec": _delta_float(getattr(ta.retrieval, "elapsed_sec", None), getattr(tb.retrieval, "elapsed_sec", None)),
            "rerank_elapsed_sec": _delta_float(getattr(ta.rerank, "elapsed_sec", None), getattr(tb.rerank, "elapsed_sec", None)),
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

