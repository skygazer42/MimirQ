from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

_REPORT_SCHEMA = "mimirq.dataset_analysis.report.v1"
_CORE_METRIC_KEYS = (
    "raw_positive_rate",
    "controllable_positive_rate",
    "knowledge_base_coverage",
    "retrieval_accuracy",
    "generation_accuracy",
)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _metric_card_rows(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    payload = dict(metrics or {})
    for key in _CORE_METRIC_KEYS:
        rows.append({"key": key, "value": payload.get(key)})
    return rows


def build_dataset_analysis_report(
    *,
    dataset_id: str,
    dataset_name: str,
    filters: dict[str, Any],
    scope_summary: dict[str, Any],
    metrics: dict[str, Any],
    counts: dict[str, Any],
    ratios: dict[str, Any],
    top_examples: dict[str, Any],
    manual_review_candidates: list[dict[str, Any]],
    glossary_candidates: list[dict[str, Any]],
    keyword_scores: list[dict[str, Any]],
    coverage_heatmap: dict[str, Any],
    umap_scatter: dict[str, Any],
    latency_breakdown: dict[str, Any],
) -> dict[str, Any]:
    return {
        "meta": {
            "dataset_id": str(dataset_id or ""),
            "dataset_name": str(dataset_name or ""),
            "filters": dict(filters or {}),
            "generated_at": _iso_now(),
            "scope_summary": dict(scope_summary or {}),
            "schema_version": _REPORT_SCHEMA,
        },
        "metrics": dict(metrics or {}),
        "metric_cards": _metric_card_rows(dict(metrics or {})),
        "feedback_coverage": {
            "key": "feedback_coverage_rate",
            "value": dict(metrics or {}).get("feedback_coverage_rate"),
        },
        "counts": dict(counts or {}),
        "ratios": dict(ratios or {}),
        "top_examples": dict(top_examples or {}),
        "manual_review_candidates": list(manual_review_candidates or []),
        "glossary_candidates": list(glossary_candidates or []),
        "keyword_scores": list(keyword_scores or []),
        "coverage_heatmap": dict(coverage_heatmap or {}),
        "umap_scatter": dict(umap_scatter or {}),
        "latency_breakdown": dict(latency_breakdown or {}),
    }
