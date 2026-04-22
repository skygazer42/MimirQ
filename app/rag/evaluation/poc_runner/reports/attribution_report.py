from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

_REPORT_SCHEMA = "mimirq.dataset_analysis.report.v1"


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


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
        "counts": dict(counts or {}),
        "ratios": dict(ratios or {}),
        "top_examples": dict(top_examples or {}),
        "manual_review_candidates": list(manual_review_candidates or []),
        "glossary_candidates": list(glossary_candidates or []),
        "keyword_scores": list(keyword_scores or []),
        "coverage_heatmap": dict(coverage_heatmap or {}),
    }
