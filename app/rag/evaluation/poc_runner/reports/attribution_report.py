
from dataclasses import dataclass
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


def _report_meta(payload: "DatasetAnalysisReportPayload") -> dict[str, Any]:
    return {
        "dataset_id": str(payload.dataset_id or ""),
        "dataset_name": str(payload.dataset_name or ""),
        "filters": dict(payload.filters or {}),
        "generated_at": _iso_now(),
        "scope_summary": dict(payload.scope_summary or {}),
        "schema_version": _REPORT_SCHEMA,
    }


def _feedback_coverage(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": "feedback_coverage_rate",
        "value": dict(metrics or {}).get("feedback_coverage_rate"),
    }


@dataclass(frozen=True)
class DatasetAnalysisReportPayload:
    dataset_id: str
    dataset_name: str
    filters: dict[str, Any]
    scope_summary: dict[str, Any]
    metrics: dict[str, Any]
    counts: dict[str, Any]
    ratios: dict[str, Any]
    top_examples: dict[str, Any]
    manual_review_candidates: list[dict[str, Any]]
    glossary_candidates: list[dict[str, Any]]
    keyword_scores: list[dict[str, Any]]
    coverage_heatmap: dict[str, Any]
    umap_scatter: dict[str, Any]
    latency_breakdown: dict[str, Any]


def build_dataset_analysis_report(payload: DatasetAnalysisReportPayload) -> dict[str, Any]:
    metrics = dict(payload.metrics or {})
    return {
        "meta": _report_meta(payload),
        "metrics": metrics,
        "metric_cards": _metric_card_rows(metrics),
        "feedback_coverage": _feedback_coverage(metrics),
        "counts": dict(payload.counts or {}),
        "ratios": dict(payload.ratios or {}),
        "top_examples": dict(payload.top_examples or {}),
        "manual_review_candidates": list(payload.manual_review_candidates or []),
        "glossary_candidates": list(payload.glossary_candidates or []),
        "keyword_scores": list(payload.keyword_scores or []),
        "coverage_heatmap": dict(payload.coverage_heatmap or {}),
        "umap_scatter": dict(payload.umap_scatter or {}),
        "latency_breakdown": dict(payload.latency_breakdown or {}),
    }
