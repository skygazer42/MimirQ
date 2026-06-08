"""Report aggregation service.

Goal:
- Provide an exportable, shareable bundle for dataset quality + compliance.
- Keep it lightweight by reusing existing summaries and limiting expensive queries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas.document_folders import DocumentFolderTreeResponse
from app.api.schemas.report import (
    ComplianceSummary,
    ConnectorRunSummary,
    DatasetChunkQualityMetricsOut,
    DatasetGovernanceAuditOut,
    DatasetGovernanceMetricsOut,
    DatasetHierarchyRecallSummaryOut,
    DatasetKGStatsOut,
    DatasetMustRecallSummaryOut,
    DatasetParseRiskDocumentOut,
    DatasetParseRiskSummaryOut,
    DatasetRegressionRunSummaryOut,
    DatasetReportDataProvenanceOut,
    DatasetReportOut,
    DatasetRetrievalAuditGateOut,
    DatasetRetrievalAuditOut,
    PipelineVersionSummary,
)
from app.core.config import settings
from app.models.connector import ConnectorRun as DBConnectorRun
from app.models.document import Document as DBDocument
from app.rag.core.logging import get_logger
from app.services.dataset_profile_service import build_dataset_documents_query, compute_dataset_profile_summary
from app.services.dataset_profile_utils import HistogramBinSpec, histogram, percentile_from_sorted
from app.services.dataset_service import DatasetService
from app.services.document_folders import build_document_folder_tree

logger = get_logger(__name__)
_SERVICE_FALLBACK_LOG_MESSAGE = "Ignoring non-critical service fallback failure: %s"
_PERCENTILE_KEYS = (
    ("p25", 25),
    ("p50", 50),
    ("p75", 75),
    ("p90", 90),
    ("p99", 99),
)
_GOVERNANCE_AUDIT_TOTAL_KEYS = (
    ("paras_dropped", "governance_paragraphs_dropped"),
    ("refs_removed", "governance_references_removed_lines"),
    ("urls_changed", "governance_urls_changed"),
    ("boiler_sections", "governance_boilerplate_removed_sections"),
    ("boiler_lines", "governance_boilerplate_removed_lines"),
    ("images_removed", "governance_images_removed"),
    ("tables_norm", "governance_tables_normalized"),
    ("table_rows_changed", "governance_table_rows_changed"),
    ("code_lines_stripped", "governance_code_lines_stripped"),
)
_CHAR_REDUCTION_BINS = (
    HistogramBinSpec("0-5%", 0, 5),
    HistogramBinSpec("5-15%", 5, 15),
    HistogramBinSpec("15-30%", 15, 30),
    HistogramBinSpec("30-50%", 30, 50),
    HistogramBinSpec("50-80%", 50, 80),
    HistogramBinSpec("80%+", 80, None),
)
_DENSITY_BINS = (
    HistogramBinSpec("0-5%", 0, 5),
    HistogramBinSpec("5-12%", 5, 12),
    HistogramBinSpec("12-20%", 12, 20),
    HistogramBinSpec("20-35%", 20, 35),
    HistogramBinSpec("35-50%", 35, 50),
    HistogramBinSpec("50%+", 50, None),
)
_HEADING_RATIO_BINS = (
    HistogramBinSpec("0-25%", 0, 25),
    HistogramBinSpec("25-50%", 25, 50),
    HistogramBinSpec("50-75%", 50, 75),
    HistogramBinSpec("75-85%", 75, 85),
    HistogramBinSpec("85-95%", 85, 95),
    HistogramBinSpec("95%+", 95, None),
)
_RETRIEVAL_AUDIT_SAFE_METRIC_KEYS = (
    "hit_at_1",
    "hit_at_3",
    "hit_at_5",
    "hit_at_20",
    "retrieval_hit_at_1",
    "retrieval_hit_at_3",
    "retrieval_hit_at_5",
    "retrieval_hit_at_20",
    "retrieval_recall",
    "retrieval_mrr",
    "retrieval_ndcg",
    "retrieval_ndcg_at_20",
    "retrieval_effective_context_rate",
    "retrieval_noise_rate",
    "expected_metadata_hit_rate",
    "expected_metadata_recall",
    "expected_metadata_cases_total",
    "expected_metadata_fields_total",
    "expected_metadata_fields_matched",
    "top_1_expected_metadata_match_rate",
    "top_3_expected_metadata_match_rate",
    "top_5_expected_metadata_match_rate",
    "kg_noise_rate",
    "answer_grounding_rate",
    "answer_key_point_recall",
    "candidate_gate_passed",
    "cases",
    "compared_metrics",
    "dify_hit_nonempty",
    "generated_answer_grounding_rate",
    "generated_answer_key_point_recall",
    "generated_answer_context_supported_rate",
    "generated_answer_policy_clean_rate",
    "generated_answer_fallback_rate",
    "mimirq_direct_nonempty",
    "mimirq_direct_schema_valid",
    "probe_errors",
    "route_count",
)
_RETRIEVAL_AUDIT_FAILURE_CATEGORY_ORDER = (
    "scope",
    "chunking",
    "ranking",
    "absence",
    "kg_noise",
    "adapter",
)


@dataclass(frozen=True)
class DatasetReportRequest:
    tenant_id: UUID
    account_id: str
    dataset_id: UUID
    pipeline_hash: str | None = None
    connector_runs_limit: int = 20


def _metadata_rows(metadatas: list[dict]) -> list[dict[str, Any]]:
    return [meta for meta in metadatas if isinstance(meta, dict)]


def _safe_int(raw: Any, default: int = 0) -> int:
    try:
        return int(raw or 0)
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_float(raw: Any, default: float = 0.0) -> float:
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError, OverflowError):
        return default


def _clamp_ratio(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _metadata_int(meta: dict[str, Any], key: str) -> int:
    return _safe_int(meta.get(key))


def _percentage_points(value: float) -> int:
    return int(round(_clamp_ratio(value) * 100.0))


def _distribution(values: list[int], bins: tuple[HistogramBinSpec, ...]) -> tuple[dict[str, int], list[dict]]:
    if not values:
        return {}, []

    sorted_values = sorted(values)
    percentiles = {name: percentile_from_sorted(sorted_values, pct) for name, pct in _PERCENTILE_KEYS}
    return percentiles, histogram(sorted_values, bins=list(bins))


def _add_counter_map(target: dict[str, int], raw: Any) -> None:
    if not isinstance(raw, dict):
        return
    for key_raw, value_raw in raw.items():
        if key_raw is None:
            continue
        key = str(key_raw)
        target[key] = target.get(key, 0) + _safe_int(value_raw)


def _add_rule_packs(target: dict[str, int], raw: Any) -> None:
    if not isinstance(raw, list):
        return

    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        target[key] = target.get(key, 0) + 1


def _char_lengths_from_persisted(raw: Any) -> tuple[int, int, bool] | None:
    if not isinstance(raw, dict):
        return None

    original = raw.get("original") if isinstance(raw.get("original"), dict) else {}
    cleaned = raw.get("cleaned") if isinstance(raw.get("cleaned"), dict) else {}
    original_len = _safe_int(original.get("raw_len"))
    cleaned_len = _safe_int(cleaned.get("raw_len"))
    if original_len <= 0 or cleaned_len < 0:
        return None

    truncated = bool(original.get("truncated")) or bool(cleaned.get("truncated"))
    return original_len, cleaned_len, truncated


def _char_lengths_from_stats(raw: Any) -> tuple[int, int] | None:
    if not isinstance(raw, dict):
        return None

    original_len = _safe_int(raw.get("original_chars"))
    cleaned_len = _safe_int(raw.get("cleaned_chars"))
    if original_len <= 0 or cleaned_len < 0:
        return None
    return original_len, cleaned_len


def _char_reduction_pct(original_len: int, cleaned_len: int) -> int:
    if original_len <= 0:
        return 0
    return _percentage_points((float(original_len) - float(cleaned_len)) / float(original_len))


def _governance_quality_percentages(meta: dict[str, Any]) -> tuple[int, int] | None:
    quality = meta.get("governance_quality")
    if not isinstance(quality, dict):
        return None

    density = _clamp_ratio(_safe_float(quality.get("density")))
    heading_ratio = _clamp_ratio(_safe_float(quality.get("heading_ratio")))
    return _percentage_points(density), _percentage_points(heading_ratio)


def _chunk_quality_grade(meta: dict[str, Any]) -> str:
    gate = meta.get("chunk_quality_gate")
    if not isinstance(gate, dict):
        return "unknown"
    return str(gate.get("grade") or "").strip().lower() or "unknown"


def _chunk_coverage_flags(meta: dict[str, Any]) -> tuple[bool, bool]:
    coverage = meta.get("chunk_coverage")
    if not isinstance(coverage, dict):
        return False, False

    ratio = _safe_float(coverage.get("coverage_ratio"))
    waste = _safe_float(coverage.get("overlap_waste_ratio"))
    return 0.0 < ratio < 0.98, waste > 0.60


def _parse_quality_score(meta: dict[str, Any]) -> float | None:
    raw = meta.get("parse_quality")
    if isinstance(raw, dict):
        raw = raw.get("score")
    if raw is None:
        return None
    try:
        return _clamp_ratio(float(raw))
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_low_quality_doc(meta: dict[str, Any], score: float) -> tuple[str, float, str, dict[str, Any]] | None:
    doc_id = str(meta.get("document_id") or "").strip()
    if not doc_id:
        return None

    reason = "parse_quality_below_threshold"
    specialty_signals: dict[str, Any] = {}
    seal_summary = meta.get("seal_summary") if isinstance(meta.get("seal_summary"), dict) else None
    if isinstance(seal_summary, dict):
        seal_score = _safe_float(seal_summary.get("primary_score"), default=1.0)
        if bool(seal_summary.get("detected")) and seal_score < 0.6:
            reason = "seal_low_confidence"
            specialty_signals = {
                "seal_confidence": round(float(seal_score), 3),
                "seal_expected": True,
            }
    return doc_id, score, reason, specialty_signals


def _parse_risk_recommendation(considered: int, high_ratio: float) -> str:
    if considered <= 0:
        return "no_parse_quality_metadata"
    if high_ratio >= 0.8:
        return "high_parse_risk_reparse_documents"
    if high_ratio >= 0.5:
        return "medium_parse_risk_prioritize_low_quality_docs"
    if high_ratio >= 0.2:
        return "monitor_parse_quality_tail"
    return "parse_quality_healthy"


def _summary_int(summary: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        if key in summary:
            return max(0, _safe_int(summary.get(key)))
    return None


def _summary_ratio(summary: dict[str, Any], key: str) -> float | None:
    raw = summary.get(key)
    if raw is None:
        return None
    try:
        return _clamp_ratio(float(raw))
    except (TypeError, ValueError, OverflowError) as exc:
        logger.debug(_SERVICE_FALLBACK_LOG_MESSAGE, exc)
        return None


def _summary_ratio_any(summary: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in summary:
            return _summary_ratio(summary, key)
    return None


def _safe_report_list(raw: Any, *, max_items: int = 20, max_len: int = 160) -> list[str]:
    values = raw if isinstance(raw, list | tuple | set) else [raw]
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        if not text or len(text) > max_len or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= max_items:
            break
    return out


def _safe_report_text(raw: Any, *, max_len: int = 160) -> str | None:
    text = str(raw or "").strip()
    if not text or len(text) > max_len:
        return None
    return text


def _retrieval_audit_safe_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for key in _RETRIEVAL_AUDIT_SAFE_METRIC_KEYS:
        value = summary.get(key)
        if isinstance(value, bool):
            metrics[key] = bool(value)
        elif isinstance(value, int) and not isinstance(value, bool):
            metrics[key] = int(value)
        elif isinstance(value, float):
            metrics[key] = round(float(value), 6)
    return metrics


def _increment_failure(categories: dict[str, int], key: str) -> None:
    categories[key] = int(categories.get(key, 0) or 0) + 1


def _retrieval_audit_failure_categories(summary: dict[str, Any]) -> dict[str, int]:
    categories: dict[str, int] = {}
    metadata_hit = _summary_ratio_any(summary, "expected_metadata_hit_rate", "top_1_expected_metadata_match_rate")
    metadata_recall = _summary_ratio(summary, "expected_metadata_recall")
    if (metadata_hit is not None and metadata_hit < 1.0) or (metadata_recall is not None and metadata_recall < 1.0):
        _increment_failure(categories, "scope")

    effective_context = _summary_ratio(summary, "retrieval_effective_context_rate")
    retrieval_noise = _summary_ratio(summary, "retrieval_noise_rate")
    if (effective_context is not None and effective_context < 0.9) or (retrieval_noise is not None and retrieval_noise > 0.1):
        _increment_failure(categories, "chunking")

    hit_1 = _summary_ratio_any(summary, "hit_at_1", "retrieval_hit_at_1")
    hit_3 = _summary_ratio_any(summary, "hit_at_3", "retrieval_hit_at_3")
    if hit_1 is not None and hit_3 is not None and hit_3 > hit_1:
        _increment_failure(categories, "ranking")

    recall = _summary_ratio(summary, "retrieval_recall")
    if recall is not None and recall < 1.0:
        _increment_failure(categories, "absence")

    kg_noise = _summary_ratio(summary, "kg_noise_rate")
    if kg_noise is not None and kg_noise > 0.1:
        _increment_failure(categories, "kg_noise")
    return categories


def _retrieval_audit_next_action(categories: dict[str, int]) -> str:
    if not categories:
        return "Retrieval audit passed; keep golden gates fresh before production changes."
    labels = {
        "scope": "metadata scope",
        "chunking": "chunking",
        "ranking": "ranking",
        "absence": "content absence",
        "kg_noise": "KG noise",
        "adapter": "adapter binding",
    }
    ordered = [labels[key] for key in _RETRIEVAL_AUDIT_FAILURE_CATEGORY_ORDER if key in categories and key in labels]
    if not ordered:
        return "Inspect failed retrieval gates before enabling production retrieval."
    if len(ordered) == 1:
        joined = ordered[0]
    elif len(ordered) == 2:
        joined = " and ".join(ordered)
    else:
        joined = ", ".join(ordered[:-1]) + f", and {ordered[-1]}"
    return f"Fix {joined} before enabling production retrieval."


def _retrieval_audit_safe_categories(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    categories: dict[str, int] = {}
    for key in _RETRIEVAL_AUDIT_FAILURE_CATEGORY_ORDER:
        value = _safe_int(raw.get(key))
        if value > 0:
            categories[key] = value
    return categories


def _merge_failure_categories(*items: dict[str, int]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for key in _RETRIEVAL_AUDIT_FAILURE_CATEGORY_ORDER:
        total = sum(max(0, _safe_int(item.get(key))) for item in items if isinstance(item, dict))
        if total > 0:
            merged[key] = total
    return merged


def _retrieval_audit_gate_from_metadata(raw: Any) -> DatasetRetrievalAuditGateOut | None:
    if not isinstance(raw, dict):
        return None

    name = _safe_report_text(raw.get("name"), max_len=80)
    if not name:
        return None

    status = (_safe_report_text(raw.get("status"), max_len=40) or "unavailable").lower()
    source = _safe_report_text(raw.get("source"), max_len=160)
    generated_at = raw.get("generated_at")
    if isinstance(generated_at, str) and len(generated_at) > 80:
        generated_at = None

    payload = {
        "name": name,
        "status": status,
        "metrics": _retrieval_audit_safe_metrics(raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}),
        "failed_conditions": _safe_report_list(raw.get("failed_conditions"), max_items=20, max_len=160),
        "generated_at": generated_at,
        "source": source,
    }
    try:
        return DatasetRetrievalAuditGateOut(**payload)
    except Exception:
        payload["generated_at"] = None
        return DatasetRetrievalAuditGateOut(**payload)


def _retrieval_audit_from_dataset_metadata(dataset_metadata: dict[str, Any] | None) -> DatasetRetrievalAuditOut | None:
    raw = dataset_metadata.get("retrieval_audit") if isinstance(dataset_metadata, dict) else None
    if not isinstance(raw, dict):
        return None

    gates: list[DatasetRetrievalAuditGateOut] = []
    raw_gates = raw.get("gates") if isinstance(raw.get("gates"), list) else []
    for raw_gate in raw_gates:
        gate = _retrieval_audit_gate_from_metadata(raw_gate)
        if gate is not None:
            gates.append(gate)
        if len(gates) >= 20:
            break

    failure_categories = _retrieval_audit_safe_categories(raw.get("failure_categories"))
    if not failure_categories:
        derived_categories: list[dict[str, int]] = []
        for gate in gates:
            derived_categories.append(_retrieval_audit_failure_categories(dict(gate.metrics or {})))
        failure_categories = _merge_failure_categories(*derived_categories)

    status = (_safe_report_text(raw.get("status"), max_len=40) or "").lower()
    if failure_categories or status in {"failed", "error"}:
        status = "failed"
    elif not status:
        status = "passed" if gates else "unavailable"

    return DatasetRetrievalAuditOut(
        status=status,
        plugin_refs=_safe_report_list(raw.get("plugin_refs"), max_items=20, max_len=160),
        plugin_package_hashes=_safe_report_list(raw.get("plugin_package_hashes"), max_items=20, max_len=160),
        gates=gates,
        failure_categories=failure_categories,
        recommended_next_action=_retrieval_audit_next_action(failure_categories),
    )


def _retrieval_audit_from_regression_run(
    *,
    latest_regression_run: DatasetRegressionRunSummaryOut | None,
) -> DatasetRetrievalAuditOut | None:
    if latest_regression_run is None:
        return None

    summary = dict(latest_regression_run.summary or {})
    params = dict(latest_regression_run.params or {})
    failure_categories = _retrieval_audit_failure_categories(summary)
    run_status = str(latest_regression_run.status or "").strip().lower()
    status = "failed" if failure_categories or run_status in {"failed", "error"} else "passed"
    if run_status not in {"completed", "passed", "success"} and status == "passed":
        status = run_status or "unavailable"

    plugin_refs = _safe_report_list(params.get("plugin_refs") or summary.get("plugin_refs"))
    plugin_hashes = _safe_report_list(
        summary.get("plugin_package_hashes")
        or summary.get("plugin_package_hash")
        or params.get("plugin_package_hashes")
        or params.get("plugin_package_hash")
    )
    gate = DatasetRetrievalAuditGateOut(
        name="latest_regression_run",
        status=status,
        metrics=_retrieval_audit_safe_metrics(summary),
        failed_conditions=list(failure_categories),
        generated_at=latest_regression_run.finished_at or latest_regression_run.created_at,
        source="regression_runs.summary",
    )
    return DatasetRetrievalAuditOut(
        status=status,
        plugin_refs=plugin_refs,
        plugin_package_hashes=plugin_hashes,
        gates=[gate],
        failure_categories=failure_categories,
        recommended_next_action=_retrieval_audit_next_action(failure_categories),
    )


def _merge_retrieval_audits(*audits: DatasetRetrievalAuditOut | None) -> DatasetRetrievalAuditOut | None:
    valid = [audit for audit in audits if audit is not None]
    if not valid:
        return None

    failure_categories = _merge_failure_categories(*(dict(audit.failure_categories or {}) for audit in valid))
    statuses = [str(audit.status or "").strip().lower() for audit in valid]
    status = "failed" if failure_categories or any(item in {"failed", "error"} for item in statuses) else "passed"
    if status == "passed" and not any(item in {"passed", "completed", "success"} for item in statuses):
        status = next((item for item in statuses if item), "unavailable")

    gates: list[DatasetRetrievalAuditGateOut] = []
    for audit in valid:
        for gate in audit.gates:
            gates.append(gate)
            if len(gates) >= 20:
                break
        if len(gates) >= 20:
            break

    return DatasetRetrievalAuditOut(
        status=status,
        plugin_refs=_safe_report_list([ref for audit in valid for ref in audit.plugin_refs], max_items=20, max_len=160),
        plugin_package_hashes=_safe_report_list(
            [package_hash for audit in valid for package_hash in audit.plugin_package_hashes],
            max_items=20,
            max_len=160,
        ),
        gates=gates,
        failure_categories=failure_categories,
        recommended_next_action=_retrieval_audit_next_action(failure_categories),
    )


def _build_retrieval_audit_summary(
    *,
    latest_regression_run: DatasetRegressionRunSummaryOut | None,
    dataset_metadata: dict[str, Any] | None = None,
) -> DatasetRetrievalAuditOut | None:
    return _merge_retrieval_audits(
        _retrieval_audit_from_dataset_metadata(dataset_metadata),
        _retrieval_audit_from_regression_run(latest_regression_run=latest_regression_run),
    )


def _safe_dataset_report_metadata(
    dataset_metadata: dict[str, Any],
    *,
    retrieval_audit: DatasetRetrievalAuditOut | None,
) -> dict[str, Any]:
    safe_metadata = dict(dataset_metadata or {})
    if retrieval_audit is not None and isinstance(safe_metadata.get("retrieval_audit"), dict):
        if hasattr(retrieval_audit, "model_dump"):
            safe_metadata["retrieval_audit"] = retrieval_audit.model_dump(mode="json", exclude_none=True)
        else:
            safe_metadata["retrieval_audit"] = retrieval_audit.dict(exclude_none=True)
    return safe_metadata


def _normalize_must_recall_counts(
    *,
    summary: dict[str, Any],
    pass_rate: float | None,
) -> tuple[int, int, int]:
    total = _summary_int(summary, "must_recall_cases_total", "retrieval_items_total", "items_total") or 0
    passed = _summary_int(summary, "must_recall_cases_passed")
    failed = _summary_int(summary, "must_recall_cases_failed")

    if passed is None and pass_rate is not None and total > 0:
        passed = int(round(float(pass_rate) * float(total)))
    passed = max(0, min(int(passed or 0), int(total)))

    if failed is None:
        failed = max(0, int(total) - int(passed))
    failed = max(0, min(int(failed), int(total)))
    return int(total), int(passed), int(failed)


def _aggregate_governance_metrics(
    *,
    total_documents: int,
    metadatas: list[dict],
    truncated: bool,
) -> DatasetGovernanceMetricsOut:
    valid_metadatas = _metadata_rows(metadatas)
    docs_with_governance = 0
    rules_applied_total = 0
    changed_documents_total = 0
    dropped_documents_total = 0
    drop_reasons_total: dict[str, int] = {}
    rule_packs_docs: dict[str, int] = {}

    for meta in valid_metadatas:
        # Treat presence of governance_enabled or governance_version as "has governance".
        has_gov = bool(meta.get("governance_enabled")) or bool(meta.get("governance_version"))
        if has_gov:
            docs_with_governance += 1

        rules_applied_total += _metadata_int(meta, "governance_rules_applied")
        changed_documents_total += _metadata_int(meta, "governance_changed_documents")
        dropped_documents_total += _metadata_int(meta, "governance_dropped_documents")
        _add_counter_map(drop_reasons_total, meta.get("governance_drop_reasons"))
        _add_rule_packs(rule_packs_docs, meta.get("governance_rule_packs"))

    return DatasetGovernanceMetricsOut(
        total_documents=int(total_documents or 0),
        used_documents=len(valid_metadatas),
        truncated=bool(truncated),
        docs_with_governance=int(docs_with_governance),
        rules_applied_total=int(max(0, rules_applied_total)),
        changed_documents_total=int(max(0, changed_documents_total)),
        dropped_documents_total=int(max(0, dropped_documents_total)),
        drop_reasons_total={k: int(max(0, v)) for k, v in drop_reasons_total.items() if int(v or 0) > 0},
        rule_packs_docs={k: int(max(0, v)) for k, v in rule_packs_docs.items() if int(v or 0) > 0},
    )


def _aggregate_governance_audit(
    *,
    total_documents: int,
    metadatas: list[dict],
    truncated: bool,
) -> DatasetGovernanceAuditOut:
    """
    Aggregate governance *effects* metrics from document-level metadata (best-effort).

    Notes:
    - Uses only already-persisted document metadata; does not scan full text.
    - Some counters require newer ingestion runs (keys may be missing on legacy docs).
    """

    valid_metadatas = _metadata_rows(metadatas)
    docs_changed = 0
    docs_dropped = 0
    audit_totals = dict.fromkeys((name for name, _key in _GOVERNANCE_AUDIT_TOTAL_KEYS), 0)

    persisted_docs = 0
    persisted_truncated_docs = 0
    char_stats_docs = 0
    orig_chars_total = 0
    clean_chars_total = 0
    reduction_pcts: list[int] = []

    quality_docs = 0
    density_pcts: list[int] = []
    heading_ratio_pcts: list[int] = []

    for meta in valid_metadatas:
        docs_changed += int(_metadata_int(meta, "governance_changed_documents") > 0)
        docs_dropped += int(_metadata_int(meta, "governance_dropped_documents") > 0)
        for name, key in _GOVERNANCE_AUDIT_TOTAL_KEYS:
            audit_totals[name] += _metadata_int(meta, key)

        char_lengths: tuple[int, int] | None = None
        persisted = _char_lengths_from_persisted(meta.get("parsed_content_persisted"))
        if persisted is not None:
            original_len, cleaned_len, is_truncated = persisted
            persisted_docs += 1
            persisted_truncated_docs += int(is_truncated)
            char_lengths = (original_len, cleaned_len)
        else:
            fallback = _char_lengths_from_stats(meta.get("governance_char_stats"))
            if fallback is not None:
                char_lengths = fallback

        if char_lengths is not None:
            original_len, cleaned_len = char_lengths
            char_stats_docs += 1
            orig_chars_total += original_len
            clean_chars_total += cleaned_len
            # Express distributions in percentage points (0-100), aligned with DatasetProfile percentiles.
            reduction_pcts.append(_char_reduction_pct(original_len, cleaned_len))

        quality_pcts = _governance_quality_percentages(meta)
        if quality_pcts is not None:
            density_pct, heading_ratio_pct = quality_pcts
            quality_docs += 1
            density_pcts.append(density_pct)
            heading_ratio_pcts.append(heading_ratio_pct)

    ratio = 0.0
    if orig_chars_total > 0 and clean_chars_total >= 0:
        ratio = _clamp_ratio((float(orig_chars_total) - float(clean_chars_total)) / float(orig_chars_total))

    pct_percentiles, pct_hist = _distribution(reduction_pcts, _CHAR_REDUCTION_BINS)
    density_percentiles, density_hist = _distribution(density_pcts, _DENSITY_BINS)
    heading_percentiles, heading_hist = _distribution(heading_ratio_pcts, _HEADING_RATIO_BINS)

    return DatasetGovernanceAuditOut(
        total_documents=int(total_documents or 0),
        used_documents=len(valid_metadatas),
        truncated=bool(truncated),
        docs_with_parsed_content_persisted=int(persisted_docs),
        parsed_content_truncated_docs=int(persisted_truncated_docs),
        docs_with_char_stats=int(char_stats_docs),
        original_chars_total=int(max(0, orig_chars_total)),
        cleaned_chars_total=int(max(0, clean_chars_total)),
        char_reduction_ratio=float(ratio),
        char_reduction_pct_percentiles=pct_percentiles,
        char_reduction_pct_histogram=pct_hist,
        docs_changed=int(max(0, docs_changed)),
        docs_dropped=int(max(0, docs_dropped)),
        docs_with_governance_quality=int(max(0, quality_docs)),
        density_pct_percentiles=density_percentiles,
        density_pct_histogram=density_hist,
        heading_ratio_pct_percentiles=heading_percentiles,
        heading_ratio_pct_histogram=heading_hist,
        paragraphs_dropped_total=int(max(0, audit_totals["paras_dropped"])),
        references_removed_lines_total=int(max(0, audit_totals["refs_removed"])),
        urls_changed_total=int(max(0, audit_totals["urls_changed"])),
        boilerplate_removed_sections_total=int(max(0, audit_totals["boiler_sections"])),
        boilerplate_removed_lines_total=int(max(0, audit_totals["boiler_lines"])),
        images_removed_total=int(max(0, audit_totals["images_removed"])),
        tables_normalized_total=int(max(0, audit_totals["tables_norm"])),
        table_rows_changed_total=int(max(0, audit_totals["table_rows_changed"])),
        code_lines_stripped_total=int(max(0, audit_totals["code_lines_stripped"])),
    )


def _aggregate_chunk_quality_metrics(
    *,
    total_documents: int,
    metadatas: list[dict],
    truncated: bool,
) -> DatasetChunkQualityMetricsOut:
    valid_metadatas = _metadata_rows(metadatas)
    gate_grades: dict[str, int] = {}
    coverage_low = 0
    overlap_high = 0
    tokens_missing = 0

    for meta in valid_metadatas:
        grade = _chunk_quality_grade(meta)
        gate_grades[grade] = gate_grades.get(grade, 0) + 1

        has_low_coverage, has_high_overlap = _chunk_coverage_flags(meta)
        coverage_low += int(has_low_coverage)
        overlap_high += int(has_high_overlap)
        if not isinstance(meta.get("chunking_stats_tokens"), dict):
            tokens_missing += 1

    # Stable keys for UI (avoid missing keys on empty datasets).
    stable = {k: int(gate_grades.get(k, 0) or 0) for k in ("pass", "warn", "fail", "unknown")}
    # Keep any non-standard grades too (best-effort).
    for k, v in gate_grades.items():
        if k in stable:
            continue
        stable[str(k)] = int(v or 0)

    return DatasetChunkQualityMetricsOut(
        total_documents=int(total_documents or 0),
        used_documents=len(valid_metadatas),
        truncated=bool(truncated),
        gate_grade_docs=stable,
        coverage_low_documents=int(max(0, coverage_low)),
        overlap_waste_high_documents=int(max(0, overlap_high)),
        token_stats_missing_documents=int(max(0, tokens_missing)),
    )


def _aggregate_parse_risk_summary(
    *,
    total_documents: int,
    metadatas: list[dict],
    truncated: bool,
    low_threshold: float,
) -> DatasetParseRiskSummaryOut:
    valid_metadatas = _metadata_rows(metadatas)
    considered = 0
    high = 0
    medium = 0
    healthy = 0
    docs_low: list[tuple[str, float, str, dict[str, Any]]] = []
    medium_upper = min(1.0, max(float(low_threshold), float(low_threshold) + 0.2))

    for meta in valid_metadatas:
        score = _parse_quality_score(meta)
        if score is None:
            continue
        considered += 1
        if score < float(low_threshold):
            high += 1
            low_quality_doc = _parse_low_quality_doc(meta, score)
            if low_quality_doc is not None:
                docs_low.append(low_quality_doc)
        elif score < float(medium_upper):
            medium += 1
        else:
            healthy += 1

    high_ratio = (float(high) / float(considered)) if considered > 0 else 0.0
    recommendation = _parse_risk_recommendation(considered, high_ratio)

    docs_low.sort(key=lambda x: (x[1], x[0]))
    top_low = [
        DatasetParseRiskDocumentOut(
            document_id=doc_id,
            score=round(float(score), 3),
            reason=str(reason or "parse_quality_below_threshold"),
            specialty_signals=dict(specialty_signals or {}),
        )
        for doc_id, score, reason, specialty_signals in docs_low[:20]
    ]
    return DatasetParseRiskSummaryOut(
        total_documents=int(total_documents or 0),
        used_documents=len(valid_metadatas),
        truncated=bool(truncated),
        low_threshold=round(float(low_threshold), 3),
        considered_documents=int(considered),
        high_risk_documents=int(high),
        medium_risk_documents=int(medium),
        healthy_documents=int(healthy),
        high_risk_ratio=round(float(high_ratio), 3),
        recommendation=str(recommendation),
        top_low_quality_documents=top_low,
    )


def _aggregate_must_recall_summary(
    *,
    latest_regression_summary: dict[str, Any] | None,
) -> DatasetMustRecallSummaryOut | None:
    summary = latest_regression_summary if isinstance(latest_regression_summary, dict) else {}
    if not summary:
        return None

    pass_rate = _summary_ratio(summary, "must_recall_pass_rate")
    total, passed, failed = _normalize_must_recall_counts(summary=summary, pass_rate=pass_rate)

    if pass_rate is None and total > 0:
        pass_rate = float(passed) / float(total)

    status = "degraded" if total > 0 and pass_rate is not None and failed > 0 else "healthy"
    if total <= 0 or pass_rate is None:
        status = "unavailable"

    return DatasetMustRecallSummaryOut(
        pass_rate=(round(float(pass_rate), 6) if pass_rate is not None else None),
        cases_total=int(total),
        cases_passed=int(passed),
        cases_failed=int(failed),
        status=status,
    )


def _aggregate_hierarchy_recall_summary(
    *,
    latest_regression_summary: dict[str, Any] | None,
) -> DatasetHierarchyRecallSummaryOut | None:
    summary = latest_regression_summary if isinstance(latest_regression_summary, dict) else {}
    if not summary:
        return None

    def _as_ratio(*keys: str) -> float | None:
        for key in keys:
            if key not in summary:
                continue
            raw = summary.get(key)
            if raw is None:
                continue
            try:
                v = float(raw)
            except Exception:
                logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue
            v = min(1.0, max(0.0, v))
            return round(v, 6)
        return None

    doc_hit_rate = _as_ratio("retrieval_doc_hit_rate", "retrieval_doc_hit")
    family_hit_rate = _as_ratio("retrieval_family_hit_rate", "retrieval_family_hit")
    doc_recall = _as_ratio("retrieval_doc_recall")
    family_recall = _as_ratio("retrieval_family_recall")

    if doc_hit_rate is None and family_hit_rate is None and doc_recall is None and family_recall is None:
        return None

    return DatasetHierarchyRecallSummaryOut(
        doc_hit_rate=doc_hit_rate,
        family_hit_rate=family_hit_rate,
        doc_recall=doc_recall,
        family_recall=family_recall,
        status="available",
    )


def _normalize_pipeline_hash(request: DatasetReportRequest) -> str | None:
    return str(request.pipeline_hash or "").strip() or None


def _active_pipeline_hash_expr(*, default_unknown: bool = False) -> Any:
    values: list[Any] = [
        DBDocument.doc_metadata["active_pipeline_hash"].as_string(),
        DBDocument.doc_metadata["pipeline_hash"].as_string(),
    ]
    if default_unknown:
        values.append("unknown")
    return func.coalesce(*values)


def _report_documents_query(db: Session, request: DatasetReportRequest, pipeline_hash_norm: str | None) -> Any:
    _dataset, query = build_dataset_documents_query(
        db,
        tenant_id=request.tenant_id,
        account_id=request.account_id,
        dataset_id=request.dataset_id,
    )
    if pipeline_hash_norm:
        query = query.filter(_active_pipeline_hash_expr() == pipeline_hash_norm)
    return query


def _build_compliance_summary(profile: Any) -> ComplianceSummary:
    by_status = {str(k): int(v or 0) for k, v in (getattr(profile, "by_status", None) or {}).items()}
    return ComplianceSummary(
        pii_hits_total={str(k): int(v or 0) for k, v in (getattr(profile, "pii_hits_total", None) or {}).items()},
        secrets_hits_total={str(k): int(v or 0) for k, v in (getattr(profile, "secrets_hits_total", None) or {}).items()},
        quarantined_documents=int(by_status.get("quarantined", 0) or 0),
        failed_documents=int(by_status.get("failed", 0) or 0),
    )


def _load_pipeline_versions(db: Session, request: DatasetReportRequest) -> list[PipelineVersionSummary]:
    try:
        _dataset, query = build_dataset_documents_query(
            db,
            tenant_id=request.tenant_id,
            account_id=request.account_id,
            dataset_id=request.dataset_id,
        )
        active_expr = _active_pipeline_hash_expr(default_unknown=True)
        rows = (
            query.with_entities(active_expr.label("ph"), func.count(DBDocument.id).label("cnt"))
            .group_by(active_expr)
            .order_by(func.count(DBDocument.id).desc())
            .limit(50)
            .all()
        )
        return [
            PipelineVersionSummary(
                pipeline_hash=str(getattr(row, "ph", None) or "unknown")[:64],
                documents=max(0, int(getattr(row, "cnt", 0) or 0)),
            )
            for row in rows
        ]
    except Exception:
        return []


def _load_pipeline_snapshots(
    db: Session,
    request: DatasetReportRequest,
    *,
    pipeline_hash_norm: str | None,
    pipeline_versions: list[PipelineVersionSummary],
) -> dict[str, dict]:
    targets = [str(v.pipeline_hash or "").strip() for v in (pipeline_versions or [])]
    targets = [target for target in targets if target and target != "unknown"][:10]
    target_set = set(targets)
    if not target_set:
        return {}

    try:
        from app.services.pipeline_provenance_service import build_pipeline_version_snapshot

        query = _report_documents_query(db, request, pipeline_hash_norm)
        active_expr = _active_pipeline_hash_expr(default_unknown=True)
        rows = (
            query.with_entities(active_expr.label("ph"), DBDocument.doc_metadata)
            .order_by(DBDocument.updated_at.desc())
            .limit(2000)
            .all()
        )
        snapshots: dict[str, dict] = {}
        for ph_raw, meta in rows:
            ph = str(ph_raw or "unknown")[:64]
            if ph not in target_set or ph in snapshots:
                continue
            meta_dict = meta if isinstance(meta, dict) else {}
            versions = meta_dict.get("pipeline_provenance_versions")
            snap = versions.get(ph) if isinstance(versions, dict) else None
            snapshots[ph] = dict(snap) if isinstance(snap, dict) and snap else build_pipeline_version_snapshot(meta=meta_dict, pipeline_hash=ph)
            if len(snapshots) >= len(target_set):
                break
        return snapshots
    except Exception:
        return {}


def _load_connector_runs(db: Session, request: DatasetReportRequest) -> list[ConnectorRunSummary]:
    try:
        limit = max(0, min(int(request.connector_runs_limit or 0), 100))
    except (TypeError, ValueError, OverflowError):
        limit = 20
    if limit <= 0:
        return []

    try:
        rows = (
            db.query(DBConnectorRun)
            .filter(DBConnectorRun.tenant_id == request.tenant_id, DBConnectorRun.dataset_id == request.dataset_id)
            .order_by(DBConnectorRun.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            ConnectorRunSummary(
                id=row.id,
                connector_id=str(getattr(row, "connector_id", "") or ""),
                status=str(getattr(row, "status", "") or ""),
                created_at=getattr(row, "created_at", datetime.now(UTC)),
                finished_at=getattr(row, "finished_at", None),
                error_message=getattr(row, "error_message", None),
                stats=dict(getattr(row, "stats", None) or {}),
            )
            for row in rows
        ]
    except Exception:
        return []


def _load_folder_tree(
    db: Session,
    request: DatasetReportRequest,
    *,
    pipeline_hash_norm: str | None,
    total_documents: int,
) -> DocumentFolderTreeResponse | None:
    try:
        query = _report_documents_query(db, request, pipeline_hash_norm)
        rows = query.with_entities(DBDocument.doc_metadata["source_path"].astext).all()  # type: ignore[attr-defined]
        source_paths = [row[0] for row in rows if isinstance(row, tuple) and isinstance(row[0], str) and row[0].strip()]
        root = build_document_folder_tree(source_paths, total_documents=total_documents, max_depth=20)
        return DocumentFolderTreeResponse(
            dataset_id=request.dataset_id,
            total_documents=total_documents,
            total_with_source_path=int(len(source_paths)),
            root=root,
        )
    except Exception:
        return None


def _count_events_with_page_ref(db: Session, kg_source_event: Any, allowed_ids: Any, request: DatasetReportRequest) -> int:
    try:
        page_expr = kg_source_event.references["page"].as_integer()  # type: ignore[index]
        return int(
            db.query(func.count(kg_source_event.id))
            .filter(
                kg_source_event.tenant_id == request.tenant_id,
                kg_source_event.document_id.in_(allowed_ids),
                page_expr.isnot(None),
                page_expr > 0,
            )
            .scalar()
            or 0
        )
    except Exception:
        try:
            ref_rows = (
                db.query(kg_source_event.references)
                .filter(kg_source_event.tenant_id == request.tenant_id, kg_source_event.document_id.in_(allowed_ids))
                .limit(5000)
                .all()
            )
            return sum(1 for (refs,) in ref_rows if isinstance(refs, dict) and _safe_int(refs.get("page")) > 0)
        except Exception:
            return 0


def _count_links_with_page_ref(
    db: Session,
    kg_event_entity: Any,
    kg_source_event: Any,
    allowed_ids: Any,
    request: DatasetReportRequest,
) -> int:
    try:
        page_expr = kg_event_entity.extra_data["page"].as_integer()  # type: ignore[index]
        return int(
            db.query(func.count(kg_event_entity.id))
            .join(kg_source_event, kg_source_event.id == kg_event_entity.event_id)
            .filter(
                kg_source_event.tenant_id == request.tenant_id,
                kg_source_event.document_id.in_(allowed_ids),
                page_expr.isnot(None),
                page_expr > 0,
            )
            .scalar()
            or 0
        )
    except Exception:
        try:
            extra_rows = (
                db.query(kg_event_entity.extra_data)
                .join(kg_source_event, kg_source_event.id == kg_event_entity.event_id)
                .filter(kg_source_event.tenant_id == request.tenant_id, kg_source_event.document_id.in_(allowed_ids))
                .limit(5000)
                .all()
            )
            return sum(1 for (extra,) in extra_rows if isinstance(extra, dict) and _safe_int(extra.get("page")) > 0)
        except Exception:
            return 0


def _load_kg_document_audit(query: Any) -> dict[str, Any]:
    try:
        kg_event_expr = func.coalesce(DBDocument.doc_metadata["kg_event_count"].as_integer(), 0)
        skipped_expr = func.coalesce(DBDocument.doc_metadata["kg_skipped_chunks"].as_integer(), 0)
        skipped_short_expr = func.coalesce(DBDocument.doc_metadata["kg_skipped_short_chunks"].as_integer(), 0)
        failed_expr = func.coalesce(DBDocument.doc_metadata["kg_failed_chunks"].as_integer(), 0)
        retry_expr = func.coalesce(DBDocument.doc_metadata["kg_retry_chunks"].as_integer(), 0)
        top_rows = (
            query.with_entities(
                DBDocument.id.label("document_id"),
                DBDocument.doc_metadata["source"].as_string().label("source"),
                kg_event_expr.label("event_count"),
                skipped_expr.label("skipped_chunks"),
                skipped_short_expr.label("skipped_short_chunks"),
                failed_expr.label("failed_chunks"),
                retry_expr.label("retry_chunks"),
            )
            .order_by(kg_event_expr.desc(), DBDocument.updated_at.desc())
            .limit(20)
            .all()
        )
        return {
            "documents_with_kg_extracted_at": int(query.filter(DBDocument.doc_metadata["kg_extracted_at"].as_string().isnot(None)).count()),
            "documents_with_kg_events": int(query.filter(kg_event_expr > 0).count()),
            "event_count_from_documents": int((query.with_entities(func.coalesce(func.sum(kg_event_expr), 0)).scalar() or 0)),
            "skipped_chunks_total": int((query.with_entities(func.coalesce(func.sum(skipped_expr), 0)).scalar() or 0)),
            "skipped_short_chunks_total": int((query.with_entities(func.coalesce(func.sum(skipped_short_expr), 0)).scalar() or 0)),
            "failed_chunks_total": int((query.with_entities(func.coalesce(func.sum(failed_expr), 0)).scalar() or 0)),
            "retry_chunks_total": int((query.with_entities(func.coalesce(func.sum(retry_expr), 0)).scalar() or 0)),
            "top_documents": [_kg_top_document(row) for row in top_rows if getattr(row, "document_id", None)],
        }
    except Exception:
        return {
            "documents_with_kg_extracted_at": 0,
            "documents_with_kg_events": 0,
            "event_count_from_documents": 0,
            "skipped_chunks_total": 0,
            "skipped_short_chunks_total": 0,
            "failed_chunks_total": 0,
            "retry_chunks_total": 0,
            "top_documents": [],
        }


def _kg_top_document(row: Any) -> dict[str, Any]:
    return {
        "document_id": getattr(row, "document_id", None),
        "source": getattr(row, "source", None),
        "event_count": int(getattr(row, "event_count", 0) or 0),
        "skipped_chunks": int(getattr(row, "skipped_chunks", 0) or 0),
        "skipped_short_chunks": int(getattr(row, "skipped_short_chunks", 0) or 0),
        "failed_chunks": int(getattr(row, "failed_chunks", 0) or 0),
        "retry_chunks": int(getattr(row, "retry_chunks", 0) or 0),
    }


def _load_kg_stats(db: Session, request: DatasetReportRequest, pipeline_hash_norm: str | None) -> DatasetKGStatsOut | None:
    try:
        if not bool(getattr(settings, "KG_ENABLED", False)):
            return None

        from app.rag.kg.models import KgEntity, KgEventEntity, KgSourceEvent

        query = _report_documents_query(db, request, pipeline_hash_norm)
        doc_ids_subq = query.with_entities(DBDocument.id).subquery()
        allowed_ids = select(doc_ids_subq.c.id)
        event_count = int(
            db.query(func.count(KgSourceEvent.id))
            .filter(KgSourceEvent.tenant_id == request.tenant_id, KgSourceEvent.document_id.in_(allowed_ids))
            .scalar()
            or 0
        )
        link_count = int(
            db.query(func.count(KgEventEntity.id))
            .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
            .filter(KgSourceEvent.tenant_id == request.tenant_id, KgSourceEvent.document_id.in_(allowed_ids))
            .scalar()
            or 0
        )
        links_with_provenance = int(
            db.query(func.count(KgEventEntity.id))
            .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
            .filter(
                KgSourceEvent.tenant_id == request.tenant_id,
                KgSourceEvent.document_id.in_(allowed_ids),
                KgEventEntity.extra_data.isnot(None),
            )
            .scalar()
            or 0
        )
        entity_count = int(
            db.query(func.count(func.distinct(KgEventEntity.entity_id)))
            .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
            .filter(KgSourceEvent.tenant_id == request.tenant_id, KgSourceEvent.document_id.in_(allowed_ids))
            .scalar()
            or 0
        )
        updated_at = (
            db.query(func.max(KgSourceEvent.updated_at))
            .filter(KgSourceEvent.tenant_id == request.tenant_id, KgSourceEvent.document_id.in_(allowed_ids))
            .scalar()
        )
        type_rows = (
            db.query(KgEntity.type, func.count(func.distinct(KgEntity.id)).label("cnt"))
            .join(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
            .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
            .filter(KgSourceEvent.tenant_id == request.tenant_id, KgSourceEvent.document_id.in_(allowed_ids))
            .group_by(KgEntity.type)
            .order_by(func.count(func.distinct(KgEntity.id)).desc(), KgEntity.type.asc())
            .limit(50)
            .all()
        )
        audit = _load_kg_document_audit(query)
        return DatasetKGStatsOut(
            events=event_count,
            entities=entity_count,
            links=link_count,
            events_with_document_id=event_count,
            events_with_chunk_id=int(
                db.query(func.count(KgSourceEvent.id))
                .filter(
                    KgSourceEvent.tenant_id == request.tenant_id,
                    KgSourceEvent.document_id.in_(allowed_ids),
                    KgSourceEvent.chunk_id.isnot(None),
                )
                .scalar()
                or 0
            ),
            events_with_page_ref=_count_events_with_page_ref(db, KgSourceEvent, allowed_ids, request),
            links_with_provenance=links_with_provenance,
            links_with_page_ref=_count_links_with_page_ref(db, KgEventEntity, KgSourceEvent, allowed_ids, request),
            entity_types=[{"type": str(t or "unknown"), "count": int(cnt or 0)} for (t, cnt) in type_rows],
            updated_at=updated_at,
            **audit,
        )
    except Exception:
        return None


def _load_latest_regression_summaries(
    db: Session,
    request: DatasetReportRequest,
) -> tuple[DatasetRegressionRunSummaryOut | None, DatasetMustRecallSummaryOut | None, DatasetHierarchyRecallSummaryOut | None]:
    try:
        from app.models.evaluation import RagasRegressionRun

        row = (
            db.query(RagasRegressionRun)
            .filter(RagasRegressionRun.tenant_id == request.tenant_id, RagasRegressionRun.dataset_id == request.dataset_id)
            .order_by(RagasRegressionRun.created_at.desc())
            .first()
        )
        if row is None:
            return None, None, None

        row_summary = dict(getattr(row, "summary", None) or {})
        latest = DatasetRegressionRunSummaryOut(
            run_id=row.id,
            status=str(getattr(row, "status", "") or ""),
            metrics=list(getattr(row, "metrics", None) or []),
            params=dict(getattr(row, "params", None) or {}),
            summary=row_summary,
            error_message=getattr(row, "error_message", None),
            created_at=getattr(row, "created_at", None),
            started_at=getattr(row, "started_at", None),
            finished_at=getattr(row, "finished_at", None),
        )
        return latest, _aggregate_must_recall_summary(latest_regression_summary=row_summary), _aggregate_hierarchy_recall_summary(
            latest_regression_summary=row_summary,
        )
    except Exception:
        return None, None, None


def _load_report_metadatas(
    db: Session,
    request: DatasetReportRequest,
    *,
    pipeline_hash_norm: str | None,
    max_docs: int = 2000,
) -> tuple[list[dict], bool]:
    query = _report_documents_query(db, request, pipeline_hash_norm)
    rows = query.with_entities(DBDocument.id, DBDocument.doc_metadata).order_by(DBDocument.updated_at.desc()).limit(max_docs + 1).all()
    metadatas: list[dict] = []
    for row in rows:
        if not isinstance(row, tuple) or len(row) != 2:
            continue
        doc_id, meta_raw = row
        if not isinstance(meta_raw, dict):
            continue
        meta = dict(meta_raw)
        if meta.get("document_id") is None:
            meta["document_id"] = str(doc_id)
        metadatas.append(meta)

    truncated = len(metadatas) > max_docs
    return metadatas[:max_docs] if truncated else metadatas, truncated


def _load_metadata_summaries(
    db: Session,
    request: DatasetReportRequest,
    *,
    pipeline_hash_norm: str | None,
    total_documents: int,
) -> tuple[
    DatasetGovernanceMetricsOut | None,
    DatasetGovernanceAuditOut | None,
    DatasetChunkQualityMetricsOut | None,
    DatasetParseRiskSummaryOut | None,
]:
    try:
        metadatas, truncated = _load_report_metadatas(db, request, pipeline_hash_norm=pipeline_hash_norm)
        try:
            low_threshold = float(getattr(settings, "RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD", 0.35) or 0.35)
        except Exception:
            low_threshold = 0.35
        low_threshold = _clamp_ratio(low_threshold)
        return (
            _aggregate_governance_metrics(total_documents=total_documents, metadatas=metadatas, truncated=truncated),
            _aggregate_governance_audit(total_documents=total_documents, metadatas=metadatas, truncated=truncated),
            _aggregate_chunk_quality_metrics(total_documents=total_documents, metadatas=metadatas, truncated=truncated),
            _aggregate_parse_risk_summary(
                total_documents=total_documents,
                metadatas=metadatas,
                truncated=truncated,
                low_threshold=low_threshold,
            ),
        )
    except Exception:
        return None, None, None, None


def _load_precheck_summary(db: Session, request: DatasetReportRequest) -> dict | None:
    try:
        from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun

        row = (
            db.query(DBDatasetPrecheckScanRun)
            .filter(
                DBDatasetPrecheckScanRun.tenant_id == request.tenant_id,
                DBDatasetPrecheckScanRun.dataset_id == request.dataset_id,
                DBDatasetPrecheckScanRun.status == "completed",
            )
            .order_by(DBDatasetPrecheckScanRun.created_at.desc())
            .first()
        )
        raw = getattr(row, "summary", None) if row is not None else None
        return dict(raw) if isinstance(raw, dict) and raw else None
    except Exception:
        return None


class ReportService:
    @staticmethod
    def build_dataset_report(
        db: Session,
        *,
        request: DatasetReportRequest,
    ) -> DatasetReportOut:
        dataset = DatasetService.get_dataset(db, request.tenant_id, request.dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, request.account_id)

        pipeline_hash_norm = _normalize_pipeline_hash(request)
        profile = compute_dataset_profile_summary(
            db,
            tenant_id=request.tenant_id,
            account_id=request.account_id,
            dataset_id=request.dataset_id,
            pipeline_hash=pipeline_hash_norm,
        )
        total_documents = int(getattr(profile, "total_documents", 0) or 0)
        pipeline_versions = _load_pipeline_versions(db, request)
        latest_regression_run, must_recall_summary, hierarchy_recall_summary = _load_latest_regression_summaries(db, request)
        governance_metrics, governance_audit, chunk_quality_metrics, parse_risk_summary = _load_metadata_summaries(
            db,
            request,
            pipeline_hash_norm=pipeline_hash_norm,
            total_documents=total_documents,
        )
        dataset_metadata = dict(getattr(dataset, "dataset_metadata", None) or {})
        retrieval_audit = _build_retrieval_audit_summary(
            latest_regression_run=latest_regression_run,
            dataset_metadata=dataset_metadata,
        )

        return DatasetReportOut(
            dataset_id=request.dataset_id,
            dataset_name=str(getattr(dataset, "name", "") or "") or None,
            pipeline_hash=pipeline_hash_norm,
            generated_at=datetime.now(UTC),
            data_provenance=DatasetReportDataProvenanceOut(),
            profile=profile,
            compliance=_build_compliance_summary(profile),
            pipeline_versions=pipeline_versions,
            pipeline_snapshots=_load_pipeline_snapshots(
                db,
                request,
                pipeline_hash_norm=pipeline_hash_norm,
                pipeline_versions=pipeline_versions,
            ),
            connectors=_load_connector_runs(db, request),
            dataset_metadata=_safe_dataset_report_metadata(dataset_metadata, retrieval_audit=retrieval_audit),
            folder_tree=_load_folder_tree(
                db,
                request,
                pipeline_hash_norm=pipeline_hash_norm,
                total_documents=total_documents,
            ),
            governance_metrics=governance_metrics,
            governance_audit=governance_audit,
            chunk_quality_metrics=chunk_quality_metrics,
            parse_risk_summary=parse_risk_summary,
            kg_stats=_load_kg_stats(db, request, pipeline_hash_norm),
            latest_regression_run=latest_regression_run,
            retrieval_audit=retrieval_audit,
            must_recall_summary=must_recall_summary,
            hierarchy_recall_summary=hierarchy_recall_summary,
            precheck_summary=_load_precheck_summary(db, request),
        )
