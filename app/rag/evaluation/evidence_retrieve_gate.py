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


import math
from collections.abc import Iterable
from typing import Any

from app.rag.core.logging import get_logger
from app.rag.evaluation.regression_sample_builder import (
    build_expected_metadata_metrics_summary,
    build_regression_sample,
)

logger = get_logger(__name__)


def compute_retrieval_item_meta(
    *,
    case: dict[str, Any],
    citations: list[dict[str, Any]],
    retrieval_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    out = dict(meta or {})
    must_recall_passed = out.get("must_recall_passed")
    if must_recall_passed is None:
        rr = out.get("retrieval_recall")
        try:
            rr_float = float(rr) if rr is not None else None
        except Exception:
            rr_float = None
    if rr_float is not None:
        must_recall_passed = bool(rr_float >= 0.9999)
    else:
        must_recall_passed = None
    if must_recall_passed is None:
        must_recall_status = "unknown"
    else:
        must_recall_status = "passed" if bool(must_recall_passed) else "failed"
    out["must_recall_passed"] = must_recall_passed
    out["must_recall_status"] = must_recall_status
    metrics = retrieval_metrics if isinstance(retrieval_metrics, dict) else {}
    for key in (
        "parse_quality_alert",
        "parse_quality_low_ratio",
        "parse_risk_level",
        "parse_risk_score",
        "parse_quality_gate_profile",
        "parse_quality_gate_blocked",
    ):
        if key in metrics:
            out[key] = metrics.get(key)

    capsule = metrics.get("evidence_capsule")
    provenance_integrity_passed: bool | None = None
    if isinstance(capsule, dict):
        has_capsule_hash = bool(str(capsule.get("capsule_hash") or "").strip())
        cits = capsule.get("citations")
        has_citation_hashes = True
        if isinstance(cits, list):
            for row in cits:
                if not isinstance(row, dict):
                    continue
                if not str(row.get("citation_hash") or "").strip():
                    has_citation_hashes = False
                    break
        else:
            has_citation_hashes = False
        provenance_integrity_passed = bool(has_capsule_hash and has_citation_hashes)
    out["provenance_integrity_passed"] = provenance_integrity_passed
    return out


def _mean(values: Iterable[float | None]) -> float | None:
    vals: list[float] = []
    for v in values:
        if v is None:
            continue
        try:
            fv = float(v)
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
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

    must_recall_values = []
    for m in (items_meta or []):
        if not isinstance(m, dict):
            continue
        v = m.get("must_recall_passed")
        if v is None:
            continue
        must_recall_values.append(1 if bool(v) else 0)
    must_recall_cases_total = int(len(must_recall_values))
    must_recall_cases_passed = int(sum(must_recall_values))
    must_recall_cases_failed = int(max(0, must_recall_cases_total - must_recall_cases_passed))
    must_recall_pass_rate = (
        float(must_recall_cases_passed) / float(must_recall_cases_total)
        if must_recall_cases_total > 0
        else None
    )

    parse_alert_values = []
    parse_gate_block_values = []
    parse_risk_levels: list[str] = []
    parse_risk_scores: list[float] = []
    for m in (items_meta or []):
        if not isinstance(m, dict):
            continue
        if m.get("parse_quality_alert") is not None:
            parse_alert_values.append(1 if bool(m.get("parse_quality_alert")) else 0)
        if m.get("parse_quality_gate_blocked") is not None:
            parse_gate_block_values.append(1 if bool(m.get("parse_quality_gate_blocked")) else 0)
        lvl = str(m.get("parse_risk_level") or "").strip().lower()
        if lvl:
            parse_risk_levels.append(lvl)
        raw_score = m.get("parse_risk_score")
        try:
            if raw_score is not None:
                parse_risk_scores.append(float(raw_score))
        except Exception as exc:
            logger.debug("Ignoring retrieval gate parse-risk score coercion failure: %s", exc)
    parse_cases_total = int(len(parse_risk_levels))
    parse_risk_high_cases = int(sum(1 for lvl in parse_risk_levels if lvl == "high"))
    parse_risk_medium_cases = int(sum(1 for lvl in parse_risk_levels if lvl == "medium"))
    parse_risk_unknown_cases = int(sum(1 for lvl in parse_risk_levels if lvl == "unknown"))
    parse_risk_high_rate = (
        float(parse_risk_high_cases) / float(parse_cases_total)
        if parse_cases_total > 0
        else None
    )

    provenance_values = []
    for m in (items_meta or []):
        if not isinstance(m, dict):
            continue
        v = m.get("provenance_integrity_passed")
        if v is None:
            continue
        provenance_values.append(1 if bool(v) else 0)
    provenance_cases_total = int(len(provenance_values))
    provenance_cases_passed = int(sum(provenance_values))
    provenance_cases_failed = int(max(0, provenance_cases_total - provenance_cases_passed))
    provenance_integrity_rate = (
        float(provenance_cases_passed) / float(provenance_cases_total)
        if provenance_cases_total > 0
        else None
    )

    out = {
        "retrieval_recall": _mean(m.get("retrieval_recall") for m in (items_meta or []) if isinstance(m, dict)),
        "retrieval_doc_recall": _mean(m.get("retrieval_doc_recall") for m in (items_meta or []) if isinstance(m, dict)),
        "retrieval_family_recall": _mean(m.get("retrieval_family_recall") for m in (items_meta or []) if isinstance(m, dict)),
        "retrieval_mrr": _mean(m.get("retrieval_mrr") for m in (items_meta or []) if isinstance(m, dict)),
        "retrieval_ndcg_at_10": _mean(m.get("retrieval_ndcg_at_10") for m in (items_meta or []) if isinstance(m, dict)),
        "retrieval_ndcg_at_20": _mean(m.get("retrieval_ndcg_at_20") for m in (items_meta or []) if isinstance(m, dict)),
        "retrieval_hit_at_1": _mean_bool("retrieval_hit_at_1"),
        "retrieval_hit_at_3": _mean_bool("retrieval_hit_at_3"),
        "retrieval_hit_at_5": _mean_bool("retrieval_hit_at_5"),
        "retrieval_hit_at_10": _mean_bool("retrieval_hit_at_10"),
        "retrieval_hit_at_20": _mean_bool("retrieval_hit_at_20"),
        "retrieval_doc_hit_rate": _mean_bool("retrieval_doc_hit"),
        "retrieval_family_hit_rate": _mean_bool("retrieval_family_hit"),
        "abstain_rate": _mean_bool("abstain_triggered"),
        "must_recall_pass_rate": must_recall_pass_rate,
        "must_recall_cases_total": must_recall_cases_total,
        "must_recall_cases_passed": must_recall_cases_passed,
        "must_recall_cases_failed": must_recall_cases_failed,
        "parse_quality_alert_rate": _mean(parse_alert_values),
        "parse_quality_gate_block_rate": _mean(parse_gate_block_values),
        "parse_risk_cases_total": parse_cases_total,
        "parse_risk_high_cases": parse_risk_high_cases,
        "parse_risk_medium_cases": parse_risk_medium_cases,
        "parse_risk_unknown_cases": parse_risk_unknown_cases,
        "parse_risk_high_rate": parse_risk_high_rate,
        "parse_risk_score_mean": _mean(parse_risk_scores),
        "provenance_integrity_rate": provenance_integrity_rate,
        "provenance_cases_total": provenance_cases_total,
        "provenance_cases_passed": provenance_cases_passed,
        "provenance_cases_failed": provenance_cases_failed,
    }
    out.update(build_expected_metadata_metrics_summary([m for m in (items_meta or []) if isinstance(m, dict)]))
    return out
