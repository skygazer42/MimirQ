"""
Retrieval-only regression gate helpers for the Evidence API.

Why this exists:
- The main RAGAS regression runner can operate in "retrieval_only" mode, but it
  uses the LangGraph retrieval node.
- The Evidence API (`POST /api/v1/rag/retrieve`) is a separate, stable contract
  for downstream "evidence discovery" systems and must be gateable independently.

This module provides small, deterministic helpers:
- compute per-case retrieval metrics from (reference_sources vs citations)
- aggregate summary metrics for CI gates (Hit@K/MRR/Recall/NDCG, abstain rate)
"""

from __future__ import annotations

import math
from typing import Any, Iterable

from app.rag.evaluation.regression_sample_builder import build_regression_sample


def compute_retrieval_item_meta(*, case: dict[str, Any], citations: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Compute retrieval-only metrics for a single case given retrieved citations.

    Inputs:
    - case.reference_sources: list[dict] with at least chunk_id and (optionally) doc_pipeline_key/chunk_index/quote
    - citations: list[dict] returned by Evidence API / retrieval orchestrator

    Returns:
    - A dict containing retrieval metrics fields (retrieval_recall, retrieval_mrr, retrieval_hit_at_10, ...).
    """
    _sample_kwargs, meta = build_regression_sample(
        case,
        {
            # BuildRegressionSample is pure-ish and only needs citations + reference_sources for retrieval metrics.
            "question": str(case.get("question") or ""),
            "response": "",
            "retrieved_contexts": [],
            "citations": list(citations or []),
            "abstain_triggered": False,
            "abstain_reason": None,
        },
    )
    return dict(meta or {})


def _mean(values: Iterable[float | None]) -> float | None:
    vals: list[float] = []
    for v in values:
        if v is None:
            continue
        try:
            fv = float(v)
        except Exception:
            continue
        if math.isnan(fv):
            continue
        vals.append(fv)
    if not vals:
        return None
    return sum(vals) / len(vals)


def build_retrieval_gate_summary(items_meta: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Aggregate retrieval-only metrics across items.

    This mirrors the "retrieval gate" summary in RAGAS regression runs, but is
    intentionally decoupled so Evidence API gating can reuse it.
    """

    def _mean_bool(key: str) -> float | None:
        vals: list[float] = []
        for m in items_meta or []:
            if not isinstance(m, dict):
                continue
            v = m.get(key)
            if v is None:
                continue
            vals.append(1.0 if bool(v) else 0.0)
        return _mean(vals)

    return {
        "retrieval_recall": _mean(m.get("retrieval_recall") for m in (items_meta or []) if isinstance(m, dict)),
        "retrieval_mrr": _mean(m.get("retrieval_mrr") for m in (items_meta or []) if isinstance(m, dict)),
        "retrieval_ndcg_at_10": _mean(m.get("retrieval_ndcg_at_10") for m in (items_meta or []) if isinstance(m, dict)),
        "retrieval_ndcg_at_20": _mean(m.get("retrieval_ndcg_at_20") for m in (items_meta or []) if isinstance(m, dict)),
        "retrieval_hit_at_1": _mean_bool("retrieval_hit_at_1"),
        "retrieval_hit_at_3": _mean_bool("retrieval_hit_at_3"),
        "retrieval_hit_at_5": _mean_bool("retrieval_hit_at_5"),
        "retrieval_hit_at_10": _mean_bool("retrieval_hit_at_10"),
        "retrieval_hit_at_20": _mean_bool("retrieval_hit_at_20"),
        "abstain_rate": _mean_bool("abstain_triggered"),
    }

