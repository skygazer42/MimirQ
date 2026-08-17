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

from app.rag.core.evidence_capsule_builder import build_evidence_capsule, validate_evidence_capsule
from app.rag.core.logging import get_logger
from app.rag.evaluation.regression_sample_builder import (
    build_expected_metadata_metrics_summary,
    build_regression_sample,
)

logger = get_logger(__name__)


def _case_question(case: Any) -> str:
    if isinstance(case, dict):
        return str(case.get("question") or "")
    return str(getattr(case, "question", "") or "")


def _base_retrieval_meta(
    *,
    case: Any,
    question: str,
    citations: list[dict[str, Any]],
    base_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    if isinstance(base_meta, dict):
        return dict(base_meta)
    _sample_kwargs, meta = build_regression_sample(
        case,
        {
            "question": question,
            "response": "",
            "retrieved_contexts": [],
            "citations": list(citations or []),
            "abstain_triggered": False,
            "abstain_reason": None,
        },
    )
    return dict(meta or {})


def _must_recall_result(meta: dict[str, Any]) -> tuple[bool | None, str]:
    passed = meta.get("must_recall_passed")
    if passed is None:
        recall = meta.get("retrieval_recall")
        try:
            recall_value = float(recall) if recall is not None else None
        except Exception:
            recall_value = None
        passed = bool(recall_value >= 0.9999) if recall_value is not None else None
    if passed is None:
        return None, "unknown"
    return passed, "passed" if bool(passed) else "failed"


def _copy_parse_quality_metrics(out: dict[str, Any], metrics: dict[str, Any]) -> None:
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


def _item_evidence_capsule(
    *,
    question: str,
    citations: list[dict[str, Any]],
    metrics: dict[str, Any],
    must_recall_passed: bool | None,
    must_recall_status: str,
) -> dict[str, Any] | None:
    capsule = metrics.get("evidence_capsule")
    if isinstance(capsule, dict):
        return capsule
    try:
        return build_evidence_capsule(
            query_for_retrieval=question,
            citations=[citation for citation in (citations or []) if isinstance(citation, dict)],
            metrics={
                **metrics,
                "must_recall_passed": must_recall_passed,
                "must_recall_status": must_recall_status,
            },
            retrieval_trace=metrics.get("retrieval_trace")
            if isinstance(metrics.get("retrieval_trace"), dict)
            else None,
            query_debug=metrics.get("query_debug") if isinstance(metrics.get("query_debug"), dict) else None,
            request_context={"surface": "ragas_regression", "mode": "retrieval_only"},
        )
    except Exception as exc:
        logger.debug("Ignoring retrieval item evidence capsule build failure: %s", exc)
        return None


def _apply_provenance_status(out: dict[str, Any], capsule: dict[str, Any] | None) -> None:
    passed: bool | None = None
    status = "unknown"
    if isinstance(capsule, dict):
        passed, _reason = validate_evidence_capsule(
            capsule,
            strict=True,
            verify_signature=False,
        )
        status = "passed" if bool(passed) else "failed"
        out["evidence_capsule"] = capsule
    out["provenance_integrity_passed"] = passed
    out["provenance_integrity_status"] = status


def compute_retrieval_item_meta(
    *,
    case: Any,
    citations: list[dict[str, Any]],
    retrieval_metrics: dict[str, Any] | None = None,
    base_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Compute retrieval-only metrics for a single case given retrieved citations.

    Inputs:
    - case.reference_sources: list[dict] with at least chunk_id and (optionally) doc_pipeline_key/chunk_index/quote
    - citations: list[dict] returned by Evidence API / retrieval orchestrator

    Returns:
    - A dict containing retrieval metrics fields (retrieval_recall, retrieval_mrr, retrieval_hit_at_10, ...).
    """
    question = _case_question(case)
    out = _base_retrieval_meta(
        case=case,
        question=question,
        citations=citations,
        base_meta=base_meta,
    )
    must_recall_passed, must_recall_status = _must_recall_result(out)
    out["must_recall_passed"] = must_recall_passed
    out["must_recall_status"] = must_recall_status
    metrics = retrieval_metrics if isinstance(retrieval_metrics, dict) else {}
    _copy_parse_quality_metrics(out, metrics)
    capsule = _item_evidence_capsule(
        question=question,
        citations=citations,
        metrics=metrics,
        must_recall_passed=must_recall_passed,
        must_recall_status=must_recall_status,
    )
    _apply_provenance_status(out, capsule)
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


def _dict_items(items_meta: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in (items_meta or []) if isinstance(item, dict)]


def _mean_bool(items: list[dict[str, Any]], key: str) -> float | None:
    values = [1.0 if bool(item.get(key)) else 0.0 for item in items if item.get(key) is not None]
    return _mean(values)


def _pass_metrics(
    items: list[dict[str, Any]],
    *,
    source_key: str,
    rate_key: str,
    total_key: str,
    passed_key: str,
    failed_key: str,
    alias_key: str,
) -> dict[str, Any]:
    values = [1 if bool(item.get(source_key)) else 0 for item in items if item.get(source_key) is not None]
    total = len(values)
    passed = sum(values)
    return {
        rate_key: float(passed) / float(total) if total > 0 else None,
        total_key: int(total),
        passed_key: int(passed),
        failed_key: int(max(0, total - passed)),
        alias_key: int(passed),
    }


def _parse_quality_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    alert_values: list[int] = []
    blocked_values: list[int] = []
    risk_levels: list[str] = []
    risk_scores: list[float] = []
    for item in items:
        if item.get("parse_quality_alert") is not None:
            alert_values.append(1 if bool(item.get("parse_quality_alert")) else 0)
        if item.get("parse_quality_gate_blocked") is not None:
            blocked_values.append(1 if bool(item.get("parse_quality_gate_blocked")) else 0)
        level = str(item.get("parse_risk_level") or "").strip().lower()
        if level:
            risk_levels.append(level)
        try:
            if item.get("parse_risk_score") is not None:
                risk_scores.append(float(item["parse_risk_score"]))
        except Exception as exc:
            logger.debug("Ignoring retrieval gate parse-risk score coercion failure: %s", exc)
    total = len(risk_levels)
    high = sum(1 for level in risk_levels if level == "high")
    return {
        "parse_quality_alert_rate": _mean(alert_values),
        "parse_quality_gate_block_rate": _mean(blocked_values),
        "parse_risk_cases_total": int(total),
        "parse_risk_high_cases": int(high),
        "parse_risk_medium_cases": int(sum(1 for level in risk_levels if level == "medium")),
        "parse_risk_unknown_cases": int(sum(1 for level in risk_levels if level == "unknown")),
        "parse_risk_high_rate": float(high) / float(total) if total > 0 else None,
        "parse_risk_score_mean": _mean(risk_scores),
    }


def _retrieval_metric_means(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "retrieval_recall": _mean(item.get("retrieval_recall") for item in items),
        "retrieval_doc_recall": _mean(item.get("retrieval_doc_recall") for item in items),
        "retrieval_family_recall": _mean(item.get("retrieval_family_recall") for item in items),
        "retrieval_mrr": _mean(item.get("retrieval_mrr") for item in items),
        "retrieval_ndcg_at_10": _mean(item.get("retrieval_ndcg_at_10") for item in items),
        "retrieval_ndcg_at_20": _mean(item.get("retrieval_ndcg_at_20") for item in items),
        "retrieval_hit_at_1": _mean_bool(items, "retrieval_hit_at_1"),
        "retrieval_hit_at_3": _mean_bool(items, "retrieval_hit_at_3"),
        "retrieval_hit_at_5": _mean_bool(items, "retrieval_hit_at_5"),
        "retrieval_hit_at_10": _mean_bool(items, "retrieval_hit_at_10"),
        "retrieval_hit_at_20": _mean_bool(items, "retrieval_hit_at_20"),
        "retrieval_doc_hit_rate": _mean_bool(items, "retrieval_doc_hit"),
        "retrieval_family_hit_rate": _mean_bool(items, "retrieval_family_hit"),
        "abstain_rate": _mean_bool(items, "abstain_triggered"),
    }


def build_retrieval_gate_summary(items_meta: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Aggregate retrieval-only metrics across items.

    This mirrors the "retrieval gate" summary in RAGAS regression runs, but is
    intentionally decoupled so Evidence API gating can reuse it.
    """

    items = _dict_items(items_meta)
    out = _retrieval_metric_means(items)
    out["total_cases"] = int(len(items))
    out.update(
        _pass_metrics(
            items,
            source_key="must_recall_passed",
            rate_key="must_recall_pass_rate",
            total_key="must_recall_cases_total",
            passed_key="must_recall_cases_passed",
            failed_key="must_recall_cases_failed",
            alias_key="must_recall_passed_cases",
        )
    )
    out.update(_parse_quality_metrics(items))
    out.update(
        _pass_metrics(
            items,
            source_key="provenance_integrity_passed",
            rate_key="provenance_integrity_rate",
            total_key="provenance_cases_total",
            passed_key="provenance_cases_passed",
            failed_key="provenance_cases_failed",
            alias_key="provenance_passed_cases",
        )
    )
    out.update(build_expected_metadata_metrics_summary(items))
    return out
