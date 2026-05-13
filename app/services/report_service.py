"""Report aggregation service.

Goal:
- Provide an exportable, shareable bundle for dataset quality + compliance.
- Keep it lightweight by reusing existing summaries and limiting expensive queries.
"""

from __future__ import annotations

from app.rag.core.logging import get_logger
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
    DatasetReportOut,
    PipelineVersionSummary,
)
from app.core.config import settings
from app.models.connector import ConnectorRun as DBConnectorRun
from app.models.document import Document as DBDocument
from app.services.dataset_profile_service import build_dataset_documents_query, compute_dataset_profile_summary
from app.services.dataset_profile_utils import HistogramBinSpec, histogram, percentile_from_sorted
from app.services.dataset_service import DatasetService
from app.services.document_folders import build_document_folder_tree

logger = get_logger(__name__)


def _aggregate_governance_metrics(
    *,
    total_documents: int,
    metadatas: list[dict],
    truncated: bool,
) -> DatasetGovernanceMetricsOut:
    docs_with_governance = 0
    rules_applied_total = 0
    changed_documents_total = 0
    dropped_documents_total = 0
    drop_reasons_total: dict[str, int] = {}
    rule_packs_docs: dict[str, int] = {}

    for meta in metadatas:
        if not isinstance(meta, dict):
            continue

        # Treat presence of governance_enabled or governance_version as "has governance".
        has_gov = bool(meta.get("governance_enabled")) or bool(meta.get("governance_version"))
        if has_gov:
            docs_with_governance += 1

        try:
            rules_applied_total += int(meta.get("governance_rules_applied") or 0)
        except Exception as exc:
            logger.debug("Ignoring non-critical service fallback failure: %s", exc)
        try:
            changed_documents_total += int(meta.get("governance_changed_documents") or 0)
        except Exception as exc:
            logger.debug("Ignoring non-critical service fallback failure: %s", exc)
        try:
            dropped_documents_total += int(meta.get("governance_dropped_documents") or 0)
        except Exception as exc:
            logger.debug("Ignoring non-critical service fallback failure: %s", exc)

        reasons = meta.get("governance_drop_reasons")
        if isinstance(reasons, dict):
            for k, v in reasons.items():
                if k is None:
                    continue
                key = str(k)
                try:
                    drop_reasons_total[key] = drop_reasons_total.get(key, 0) + int(v or 0)
                except Exception:
                    continue

        packs = meta.get("governance_rule_packs")
        if isinstance(packs, list):
            seen: set[str] = set()
            for raw in packs:
                if not isinstance(raw, str):
                    continue
                key = raw.strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                rule_packs_docs[key] = rule_packs_docs.get(key, 0) + 1

    return DatasetGovernanceMetricsOut(
        total_documents=int(total_documents or 0),
        used_documents=len([m for m in metadatas if isinstance(m, dict)]),
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

    used = len([m for m in metadatas if isinstance(m, dict)])
    docs_changed = 0
    docs_dropped = 0

    paras_dropped = 0
    refs_removed = 0
    urls_changed = 0
    boiler_sections = 0
    boiler_lines = 0
    images_removed = 0
    tables_norm = 0
    table_rows_changed = 0
    code_lines_stripped = 0

    persisted_docs = 0
    persisted_truncated_docs = 0
    char_stats_docs = 0
    orig_chars_total = 0
    clean_chars_total = 0
    reduction_pcts: list[int] = []

    quality_docs = 0
    density_pcts: list[int] = []
    heading_ratio_pcts: list[int] = []

    for meta in metadatas:
        if not isinstance(meta, dict):
            continue

        try:
            if int(meta.get("governance_changed_documents") or 0) > 0:
                docs_changed += 1
        except Exception as exc:
            logger.debug("Ignoring non-critical service fallback failure: %s", exc)
        try:
            if int(meta.get("governance_dropped_documents") or 0) > 0:
                docs_dropped += 1
        except Exception as exc:
            logger.debug("Ignoring non-critical service fallback failure: %s", exc)

        def _add_int(key: str) -> int:
            raw = meta.get(key)
            try:
                return int(raw or 0)
            except Exception:
                return 0

        paras_dropped += _add_int("governance_paragraphs_dropped")
        refs_removed += _add_int("governance_references_removed_lines")
        urls_changed += _add_int("governance_urls_changed")

        boiler_sections += _add_int("governance_boilerplate_removed_sections")
        boiler_lines += _add_int("governance_boilerplate_removed_lines")
        images_removed += _add_int("governance_images_removed")

        tables_norm += _add_int("governance_tables_normalized")
        table_rows_changed += _add_int("governance_table_rows_changed")

        code_lines_stripped += _add_int("governance_code_lines_stripped")

        # Char reduction stats:
        # Prefer persist_parsed_content (raw_len from persisted markdown), fallback to lightweight
        # governance_char_stats (privacy-safe; does not store markdown).
        persisted = meta.get("parsed_content_persisted")
        recorded_char_stats = False
        if isinstance(persisted, dict):
            orig = persisted.get("original") if isinstance(persisted.get("original"), dict) else {}
            cln = persisted.get("cleaned") if isinstance(persisted.get("cleaned"), dict) else {}
            try:
                orig_raw_len = int(orig.get("raw_len") or 0)
            except Exception:
                orig_raw_len = 0
            try:
                cln_raw_len = int(cln.get("raw_len") or 0)
            except Exception:
                cln_raw_len = 0

            if orig_raw_len > 0 and cln_raw_len >= 0:
                persisted_docs += 1
                char_stats_docs += 1
                orig_chars_total += orig_raw_len
                clean_chars_total += cln_raw_len
                if bool(orig.get("truncated")) or bool(cln.get("truncated")):
                    persisted_truncated_docs += 1
                try:
                    ratio_doc = float((orig_raw_len - cln_raw_len) / float(orig_raw_len))
                except Exception:
                    ratio_doc = 0.0
                ratio_doc = max(0.0, min(1.0, ratio_doc))
                # Express distributions in percentage points (0-100), aligned with DatasetProfile percentiles.
                reduction_pcts.append(int(round(ratio_doc * 100.0)))
                recorded_char_stats = True

        if not recorded_char_stats:
            stats = meta.get("governance_char_stats")
            if isinstance(stats, dict):
                try:
                    orig_raw_len = int(stats.get("original_chars") or 0)
                except Exception:
                    orig_raw_len = 0
                try:
                    cln_raw_len = int(stats.get("cleaned_chars") or 0)
                except Exception:
                    cln_raw_len = 0

                if orig_raw_len > 0 and cln_raw_len >= 0:
                    char_stats_docs += 1
                    orig_chars_total += orig_raw_len
                    clean_chars_total += cln_raw_len
                    try:
                        ratio_doc = float((orig_raw_len - cln_raw_len) / float(orig_raw_len))
                    except Exception:
                        ratio_doc = 0.0
                    ratio_doc = max(0.0, min(1.0, ratio_doc))
                    reduction_pcts.append(int(round(ratio_doc * 100.0)))

        # Governance quality metrics (best-effort; only present on newer ingestion runs).
        quality = meta.get("governance_quality")
        if isinstance(quality, dict):
            try:
                density = float(quality.get("density") or 0.0)
            except Exception:
                density = 0.0
            try:
                heading_ratio = float(quality.get("heading_ratio") or 0.0)
            except Exception:
                heading_ratio = 0.0

            if density < 0.0:
                density = 0.0
            if density > 1.0:
                density = 1.0
            if heading_ratio < 0.0:
                heading_ratio = 0.0
            if heading_ratio > 1.0:
                heading_ratio = 1.0

            quality_docs += 1
            density_pcts.append(int(round(density * 100.0)))
            heading_ratio_pcts.append(int(round(heading_ratio * 100.0)))

    ratio = 0.0
    if orig_chars_total > 0 and clean_chars_total >= 0:
        ratio = float((orig_chars_total - clean_chars_total) / float(orig_chars_total))
        ratio = max(0.0, min(1.0, ratio))

    pct_percentiles: dict[str, int] = {}
    pct_hist: list[dict] = []
    if reduction_pcts:
        reduction_pcts_sorted = sorted(reduction_pcts)
        pct_percentiles = {
            "p25": percentile_from_sorted(reduction_pcts_sorted, 25),
            "p50": percentile_from_sorted(reduction_pcts_sorted, 50),
            "p75": percentile_from_sorted(reduction_pcts_sorted, 75),
            "p90": percentile_from_sorted(reduction_pcts_sorted, 90),
            "p99": percentile_from_sorted(reduction_pcts_sorted, 99),
        }
        pct_hist = histogram(
            reduction_pcts_sorted,
            bins=[
                HistogramBinSpec("0-5%", 0, 5),
                HistogramBinSpec("5-15%", 5, 15),
                HistogramBinSpec("15-30%", 15, 30),
                HistogramBinSpec("30-50%", 30, 50),
                HistogramBinSpec("50-80%", 50, 80),
                HistogramBinSpec("80%+", 80, None),
            ],
        )

    density_percentiles: dict[str, int] = {}
    density_hist: list[dict] = []
    if density_pcts:
        density_sorted = sorted(density_pcts)
        density_percentiles = {
            "p25": percentile_from_sorted(density_sorted, 25),
            "p50": percentile_from_sorted(density_sorted, 50),
            "p75": percentile_from_sorted(density_sorted, 75),
            "p90": percentile_from_sorted(density_sorted, 90),
            "p99": percentile_from_sorted(density_sorted, 99),
        }
        density_hist = histogram(
            density_sorted,
            bins=[
                HistogramBinSpec("0-5%", 0, 5),
                HistogramBinSpec("5-12%", 5, 12),
                HistogramBinSpec("12-20%", 12, 20),
                HistogramBinSpec("20-35%", 20, 35),
                HistogramBinSpec("35-50%", 35, 50),
                HistogramBinSpec("50%+", 50, None),
            ],
        )

    heading_percentiles: dict[str, int] = {}
    heading_hist: list[dict] = []
    if heading_ratio_pcts:
        heading_sorted = sorted(heading_ratio_pcts)
        heading_percentiles = {
            "p25": percentile_from_sorted(heading_sorted, 25),
            "p50": percentile_from_sorted(heading_sorted, 50),
            "p75": percentile_from_sorted(heading_sorted, 75),
            "p90": percentile_from_sorted(heading_sorted, 90),
            "p99": percentile_from_sorted(heading_sorted, 99),
        }
        heading_hist = histogram(
            heading_sorted,
            bins=[
                HistogramBinSpec("0-25%", 0, 25),
                HistogramBinSpec("25-50%", 25, 50),
                HistogramBinSpec("50-75%", 50, 75),
                HistogramBinSpec("75-85%", 75, 85),
                HistogramBinSpec("85-95%", 85, 95),
                HistogramBinSpec("95%+", 95, None),
            ],
        )

    return DatasetGovernanceAuditOut(
        total_documents=int(total_documents or 0),
        used_documents=int(used),
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
        paragraphs_dropped_total=int(max(0, paras_dropped)),
        references_removed_lines_total=int(max(0, refs_removed)),
        urls_changed_total=int(max(0, urls_changed)),
        boilerplate_removed_sections_total=int(max(0, boiler_sections)),
        boilerplate_removed_lines_total=int(max(0, boiler_lines)),
        images_removed_total=int(max(0, images_removed)),
        tables_normalized_total=int(max(0, tables_norm)),
        table_rows_changed_total=int(max(0, table_rows_changed)),
        code_lines_stripped_total=int(max(0, code_lines_stripped)),
    )


def _aggregate_chunk_quality_metrics(
    *,
    total_documents: int,
    metadatas: list[dict],
    truncated: bool,
) -> DatasetChunkQualityMetricsOut:
    gate_grades: dict[str, int] = {}
    coverage_low = 0
    overlap_high = 0
    tokens_missing = 0

    for meta in metadatas:
        if not isinstance(meta, dict):
            continue

        gate = meta.get("chunk_quality_gate")
        grade = "unknown"
        if isinstance(gate, dict):
            grade = str(gate.get("grade") or "").strip().lower() or "unknown"
        gate_grades[grade] = gate_grades.get(grade, 0) + 1

        cov = meta.get("chunk_coverage")
        if isinstance(cov, dict):
            try:
                ratio = float(cov.get("coverage_ratio") or 0.0)
            except Exception:
                ratio = 0.0
            if ratio > 0.0 and ratio < 0.98:
                coverage_low += 1
            try:
                waste = float(cov.get("overlap_waste_ratio") or 0.0)
            except Exception:
                waste = 0.0
            if waste > 0.60:
                overlap_high += 1

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
        used_documents=len([m for m in metadatas if isinstance(m, dict)]),
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
    used = len([m for m in metadatas if isinstance(m, dict)])
    considered = 0
    high = 0
    medium = 0
    healthy = 0
    docs_low: list[tuple[str, float, str, dict[str, Any]]] = []
    medium_upper = min(1.0, max(float(low_threshold), float(low_threshold) + 0.2))

    for meta in metadatas:
        if not isinstance(meta, dict):
            continue
        pq = meta.get("parse_quality")
        score: float | None = None
        if isinstance(pq, dict):
            try:
                score = float(pq.get("score"))
            except Exception:
                score = None
        elif pq is not None:
            try:
                score = float(pq)
            except Exception:
                score = None
        if score is None:
            continue
        score = min(1.0, max(0.0, float(score)))
        considered += 1
        if score < float(low_threshold):
            high += 1
            doc_id = str(meta.get("document_id") or "").strip()
            if doc_id:
                reason = "parse_quality_below_threshold"
                specialty_signals: dict[str, Any] = {}
                seal_summary = meta.get("seal_summary") if isinstance(meta.get("seal_summary"), dict) else None
                if isinstance(seal_summary, dict):
                    try:
                        seal_score = float(seal_summary.get("primary_score"))
                    except Exception:
                        seal_score = None
                    if bool(seal_summary.get("detected")) and seal_score is not None and seal_score < 0.6:
                        reason = "seal_low_confidence"
                        specialty_signals = {
                            "seal_confidence": round(float(seal_score), 3),
                            "seal_expected": True,
                        }
                docs_low.append((doc_id, score, reason, specialty_signals))
        elif score < float(medium_upper):
            medium += 1
        else:
            healthy += 1

    high_ratio = (float(high) / float(considered)) if considered > 0 else 0.0
    recommendation = "parse_quality_healthy"
    if considered <= 0:
        recommendation = "no_parse_quality_metadata"
    elif high_ratio >= 0.8:
        recommendation = "high_parse_risk_reparse_documents"
    elif high_ratio >= 0.5:
        recommendation = "medium_parse_risk_prioritize_low_quality_docs"
    elif high_ratio >= 0.2:
        recommendation = "monitor_parse_quality_tail"

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
        used_documents=int(used),
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

    pass_rate_raw = summary.get("must_recall_pass_rate")
    pass_rate: float | None = None
    if pass_rate_raw is not None:
        try:
            pass_rate = min(1.0, max(0.0, float(pass_rate_raw)))
        except Exception as exc:
            logger.debug("Ignoring non-critical service fallback failure: %s", exc)
            pass_rate = None

    def _as_int(*keys: str) -> int | None:
        for key in keys:
            if key not in summary:
                continue
            try:
                return max(0, int(summary.get(key) or 0))
            except Exception:
                continue
        return None

    total = _as_int("must_recall_cases_total", "retrieval_items_total", "items_total")
    passed = _as_int("must_recall_cases_passed")
    failed = _as_int("must_recall_cases_failed")

    if total is None:
        total = 0
    if passed is None and pass_rate is not None and total > 0:
        passed = int(round(float(pass_rate) * float(total)))
    if passed is None:
        passed = 0
    passed = max(0, min(int(passed), int(total)))

    if failed is None:
        failed = max(0, int(total) - int(passed))
    failed = max(0, min(int(failed), int(total)))

    if pass_rate is None and total > 0:
        pass_rate = float(passed) / float(total)

    status = "unavailable"
    if total > 0 and pass_rate is not None:
        status = "degraded" if failed > 0 else "healthy"

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


class ReportService:
    @staticmethod
    def build_dataset_report(
        db: Session,
        *,
        tenant_id: UUID,
        account_id: str,
        dataset_id: UUID,
        pipeline_hash: str | None = None,
        connector_runs_limit: int = 20,
    ) -> DatasetReportOut:
        dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)

        pipeline_hash_norm = str(pipeline_hash or "").strip() or None

        profile = compute_dataset_profile_summary(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            pipeline_hash=pipeline_hash_norm,
        )

        by_status = {str(k): int(v or 0) for k, v in (getattr(profile, "by_status", None) or {}).items()}

        compliance = ComplianceSummary(
            pii_hits_total={str(k): int(v or 0) for k, v in (getattr(profile, "pii_hits_total", None) or {}).items()},
            secrets_hits_total={str(k): int(v or 0) for k, v in (getattr(profile, "secrets_hits_total", None) or {}).items()},
            quarantined_documents=int(by_status.get("quarantined", 0) or 0),
            failed_documents=int(by_status.get("failed", 0) or 0),
        )

        # Pipeline versions distribution (best-effort).
        pipeline_versions: list[PipelineVersionSummary] = []
        try:
            _dataset, q = build_dataset_documents_query(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)
            active_expr = func.coalesce(
                DBDocument.doc_metadata["active_pipeline_hash"].as_string(),
                DBDocument.doc_metadata["pipeline_hash"].as_string(),
                "unknown",
            )
            rows = (
                q.with_entities(active_expr.label("ph"), func.count(DBDocument.id).label("cnt"))
                .group_by(active_expr)
                .order_by(func.count(DBDocument.id).desc())
                .limit(50)
                .all()
            )
            for r in rows:
                ph = str(getattr(r, "ph", None) or "unknown")
                cnt = int(getattr(r, "cnt", 0) or 0)
                pipeline_versions.append(PipelineVersionSummary(pipeline_hash=ph[:64], documents=max(0, cnt)))
        except Exception:
            pipeline_versions = []

        # Best-effort config/provenance snapshots per pipeline_hash version (for reproducibility/debug).
        pipeline_snapshots: dict[str, dict] = {}
        try:
            # Keep it bounded: only include snapshots for the top-N pipeline versions in this report.
            targets = [str(v.pipeline_hash or "").strip() for v in (pipeline_versions or [])]
            targets = [t for t in targets if t and t != "unknown"][:10]
            target_set = set(targets)
            if target_set:
                from app.services.pipeline_provenance_service import build_pipeline_version_snapshot

                _dataset, q = build_dataset_documents_query(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)
                if pipeline_hash_norm:
                    active_expr = func.coalesce(
                        DBDocument.doc_metadata["active_pipeline_hash"].as_string(),
                        DBDocument.doc_metadata["pipeline_hash"].as_string(),
                    )
                    q = q.filter(active_expr == pipeline_hash_norm)

                active_expr = func.coalesce(
                    DBDocument.doc_metadata["active_pipeline_hash"].as_string(),
                    DBDocument.doc_metadata["pipeline_hash"].as_string(),
                    "unknown",
                )
                rows = (
                    q.with_entities(active_expr.label("ph"), DBDocument.doc_metadata)
                    .order_by(DBDocument.updated_at.desc())
                    .limit(2000)
                    .all()
                )
                for ph_raw, meta in rows:
                    ph = str(ph_raw or "unknown")[:64]
                    if ph not in target_set or ph in pipeline_snapshots:
                        continue
                    meta_dict = meta if isinstance(meta, dict) else {}
                    versions = meta_dict.get("pipeline_provenance_versions")
                    snap = versions.get(ph) if isinstance(versions, dict) else None
                    if isinstance(snap, dict) and snap:
                        pipeline_snapshots[ph] = dict(snap)
                    else:
                        pipeline_snapshots[ph] = build_pipeline_version_snapshot(meta=meta_dict, pipeline_hash=ph)

                    if len(pipeline_snapshots) >= len(target_set):
                        break
        except Exception:
            pipeline_snapshots = {}

        # Recent connector runs (best-effort).
        connectors: list[ConnectorRunSummary] = []
        try:
            lim = max(0, min(int(connector_runs_limit or 0), 100))
        except Exception:
            lim = 20
        try:
            if lim > 0:
                rows = (
                    db.query(DBConnectorRun)
                    .filter(DBConnectorRun.tenant_id == tenant_id, DBConnectorRun.dataset_id == dataset_id)
                    .order_by(DBConnectorRun.created_at.desc())
                    .limit(lim)
                    .all()
                )
                for row in rows:
                    connectors.append(
                        ConnectorRunSummary(
                            id=row.id,
                            connector_id=str(getattr(row, "connector_id", "") or ""),
                            status=str(getattr(row, "status", "") or ""),
                            created_at=getattr(row, "created_at", datetime.now(UTC)),
                            finished_at=getattr(row, "finished_at", None),
                            error_message=getattr(row, "error_message", None),
                            stats=dict(getattr(row, "stats", None) or {}),
                        )
                    )
        except Exception:
            connectors = []

        # Folder tree derived from document.metadata.source_path (best-effort).
        folder_tree: DocumentFolderTreeResponse | None = None
        try:
            _dataset, q = build_dataset_documents_query(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)
            if pipeline_hash_norm:
                active_expr = func.coalesce(
                    DBDocument.doc_metadata["active_pipeline_hash"].as_string(),
                    DBDocument.doc_metadata["pipeline_hash"].as_string(),
                )
                q = q.filter(active_expr == pipeline_hash_norm)

            rows = q.with_entities(DBDocument.doc_metadata["source_path"].astext).all()  # type: ignore[attr-defined]
            source_paths = [r[0] for r in rows if isinstance(r, tuple) and isinstance(r[0], str) and r[0].strip()]
            total_docs = int(getattr(profile, "total_documents", 0) or 0)
            root = build_document_folder_tree(source_paths, total_documents=total_docs, max_depth=20)
            folder_tree = DocumentFolderTreeResponse(
                dataset_id=dataset_id,
                total_documents=total_docs,
                total_with_source_path=int(len(source_paths)),
                root=root,
            )
        except Exception:
            folder_tree = None

        # KG stats (best-effort; requires KG_ENABLED and enforces doc-level ACL).
        kg_stats: DatasetKGStatsOut | None = None
        try:
            if bool(getattr(settings, "KG_ENABLED", False)):
                from app.rag.kg.models import KgEntity, KgEventEntity, KgSourceEvent

                _dataset, q = build_dataset_documents_query(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)
                if pipeline_hash_norm:
                    active_expr = func.coalesce(
                        DBDocument.doc_metadata["active_pipeline_hash"].as_string(),
                        DBDocument.doc_metadata["pipeline_hash"].as_string(),
                    )
                    q = q.filter(active_expr == pipeline_hash_norm)

                # Use a subquery to avoid materializing a potentially large doc-id list in Python.
                doc_ids_subq = q.with_entities(DBDocument.id).subquery()
                allowed_ids = select(doc_ids_subq.c.id)

                event_count = (
                    db.query(func.count(KgSourceEvent.id))
                    .filter(KgSourceEvent.tenant_id == tenant_id, KgSourceEvent.document_id.in_(allowed_ids))
                    .scalar()
                    or 0
                )
                events_with_document_id = int(event_count or 0)  # document_id is used in the filter above.
                events_with_chunk_id = (
                    db.query(func.count(KgSourceEvent.id))
                    .filter(
                        KgSourceEvent.tenant_id == tenant_id,
                        KgSourceEvent.document_id.in_(allowed_ids),
                        KgSourceEvent.chunk_id.isnot(None),
                    )
                    .scalar()
                    or 0
                )
                # Best-effort: page provenance is stored in event.references["page"] for PDF chunks.
                events_with_page_ref = 0
                try:
                    page_expr = KgSourceEvent.references["page"].as_integer()  # type: ignore[index]
                    events_with_page_ref = (
                        db.query(func.count(KgSourceEvent.id))
                        .filter(
                            KgSourceEvent.tenant_id == tenant_id,
                            KgSourceEvent.document_id.in_(allowed_ids),
                            page_expr.isnot(None),
                            page_expr > 0,
                        )
                        .scalar()
                        or 0
                    )
                except Exception:
                    try:
                        # Fallback: sample up to 5k rows and count in Python.
                        ref_rows = (
                            db.query(KgSourceEvent.references)
                            .filter(KgSourceEvent.tenant_id == tenant_id, KgSourceEvent.document_id.in_(allowed_ids))
                            .limit(5000)
                            .all()
                        )
                        cnt = 0
                        for (refs,) in ref_rows:
                            if not isinstance(refs, dict):
                                continue
                            try:
                                if int(refs.get("page") or 0) > 0:
                                    cnt += 1
                            except Exception:
                                continue
                        events_with_page_ref = int(cnt)
                    except Exception:
                        events_with_page_ref = 0

                link_count = (
                    db.query(func.count(KgEventEntity.id))
                    .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
                    .filter(KgSourceEvent.tenant_id == tenant_id, KgSourceEvent.document_id.in_(allowed_ids))
                    .scalar()
                    or 0
                )
                links_with_provenance = (
                    db.query(func.count(KgEventEntity.id))
                    .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
                    .filter(
                        KgSourceEvent.tenant_id == tenant_id,
                        KgSourceEvent.document_id.in_(allowed_ids),
                        KgEventEntity.extra_data.isnot(None),
                    )
                    .scalar()
                    or 0
                )
                links_with_page_ref = 0
                try:
                    page_expr2 = KgEventEntity.extra_data["page"].as_integer()  # type: ignore[index]
                    links_with_page_ref = (
                        db.query(func.count(KgEventEntity.id))
                        .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
                        .filter(
                            KgSourceEvent.tenant_id == tenant_id,
                            KgSourceEvent.document_id.in_(allowed_ids),
                            page_expr2.isnot(None),
                            page_expr2 > 0,
                        )
                        .scalar()
                        or 0
                    )
                except Exception:
                    try:
                        # Fallback: sample up to 5k join rows and count in Python.
                        extra_rows = (
                            db.query(KgEventEntity.extra_data)
                            .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
                            .filter(KgSourceEvent.tenant_id == tenant_id, KgSourceEvent.document_id.in_(allowed_ids))
                            .limit(5000)
                            .all()
                        )
                        cnt2 = 0
                        for (extra,) in extra_rows:
                            if not isinstance(extra, dict):
                                continue
                            try:
                                if int(extra.get("page") or 0) > 0:
                                    cnt2 += 1
                            except Exception:
                                continue
                        links_with_page_ref = int(cnt2)
                    except Exception:
                        links_with_page_ref = 0

                entity_count = (
                    db.query(func.count(func.distinct(KgEventEntity.entity_id)))
                    .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
                    .filter(KgSourceEvent.tenant_id == tenant_id, KgSourceEvent.document_id.in_(allowed_ids))
                    .scalar()
                    or 0
                )
                updated_at = (
                    db.query(func.max(KgSourceEvent.updated_at))
                    .filter(KgSourceEvent.tenant_id == tenant_id, KgSourceEvent.document_id.in_(allowed_ids))
                    .scalar()
                )

                type_rows = (
                    db.query(KgEntity.type, func.count(func.distinct(KgEntity.id)).label("cnt"))
                    .join(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
                    .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
                    .filter(KgSourceEvent.tenant_id == tenant_id, KgSourceEvent.document_id.in_(allowed_ids))
                    .group_by(KgEntity.type)
                    .order_by(func.count(func.distinct(KgEntity.id)).desc(), KgEntity.type.asc())
                    .limit(50)
                    .all()
                )

                # Incremental / extraction audit signals (best-effort; derived from document metadata).
                documents_with_kg_extracted_at = 0
                documents_with_kg_events = 0
                event_count_from_documents = 0
                skipped_chunks_total = 0
                skipped_short_chunks_total = 0
                failed_chunks_total = 0
                retry_chunks_total = 0
                top_docs: list[dict] = []
                try:
                    docs_with_extract = q.filter(DBDocument.doc_metadata["kg_extracted_at"].as_string().isnot(None))
                    documents_with_kg_extracted_at = int(docs_with_extract.count())

                    kg_ev_expr = func.coalesce(DBDocument.doc_metadata["kg_event_count"].as_integer(), 0)
                    documents_with_kg_events = int(q.filter(kg_ev_expr > 0).count())
                    event_count_from_documents = int((q.with_entities(func.coalesce(func.sum(kg_ev_expr), 0)).scalar() or 0))

                    skipped_expr = func.coalesce(DBDocument.doc_metadata["kg_skipped_chunks"].as_integer(), 0)
                    skipped_short_expr = func.coalesce(DBDocument.doc_metadata["kg_skipped_short_chunks"].as_integer(), 0)
                    failed_expr = func.coalesce(DBDocument.doc_metadata["kg_failed_chunks"].as_integer(), 0)
                    retry_expr = func.coalesce(DBDocument.doc_metadata["kg_retry_chunks"].as_integer(), 0)

                    skipped_chunks_total = int((q.with_entities(func.coalesce(func.sum(skipped_expr), 0)).scalar() or 0))
                    skipped_short_chunks_total = int((q.with_entities(func.coalesce(func.sum(skipped_short_expr), 0)).scalar() or 0))
                    failed_chunks_total = int((q.with_entities(func.coalesce(func.sum(failed_expr), 0)).scalar() or 0))
                    retry_chunks_total = int((q.with_entities(func.coalesce(func.sum(retry_expr), 0)).scalar() or 0))

                    top_rows = (
                        q.with_entities(
                            DBDocument.id.label("document_id"),
                            DBDocument.doc_metadata["source"].as_string().label("source"),
                            kg_ev_expr.label("event_count"),
                            skipped_expr.label("skipped_chunks"),
                            skipped_short_expr.label("skipped_short_chunks"),
                            failed_expr.label("failed_chunks"),
                            retry_expr.label("retry_chunks"),
                        )
                        .order_by(kg_ev_expr.desc(), DBDocument.updated_at.desc())
                        .limit(20)
                        .all()
                    )
                    for r in top_rows:
                        try:
                            doc_id = getattr(r, "document_id", None)
                            if not doc_id:
                                continue
                            top_docs.append(
                                {
                                    "document_id": doc_id,
                                    "source": getattr(r, "source", None),
                                    "event_count": int(getattr(r, "event_count", 0) or 0),
                                    "skipped_chunks": int(getattr(r, "skipped_chunks", 0) or 0),
                                    "skipped_short_chunks": int(getattr(r, "skipped_short_chunks", 0) or 0),
                                    "failed_chunks": int(getattr(r, "failed_chunks", 0) or 0),
                                    "retry_chunks": int(getattr(r, "retry_chunks", 0) or 0),
                                }
                            )
                        except Exception:
                            continue
                except Exception:
                    documents_with_kg_extracted_at = 0
                    documents_with_kg_events = 0
                    event_count_from_documents = 0
                    skipped_chunks_total = 0
                    skipped_short_chunks_total = 0
                    failed_chunks_total = 0
                    retry_chunks_total = 0
                    top_docs = []

                kg_stats = DatasetKGStatsOut(
                    events=int(event_count),
                    entities=int(entity_count),
                    links=int(link_count),
                    events_with_document_id=int(events_with_document_id),
                    events_with_chunk_id=int(events_with_chunk_id),
                    events_with_page_ref=int(events_with_page_ref),
                    links_with_provenance=int(links_with_provenance),
                    links_with_page_ref=int(links_with_page_ref),
                    documents_with_kg_extracted_at=int(documents_with_kg_extracted_at),
                    documents_with_kg_events=int(documents_with_kg_events),
                    event_count_from_documents=int(event_count_from_documents),
                    skipped_chunks_total=int(skipped_chunks_total),
                    skipped_short_chunks_total=int(skipped_short_chunks_total),
                    failed_chunks_total=int(failed_chunks_total),
                    retry_chunks_total=int(retry_chunks_total),
                    top_documents=top_docs,
                    entity_types=[{"type": str(t or "unknown"), "count": int(cnt or 0)} for (t, cnt) in type_rows],
                    updated_at=updated_at,
                )
        except Exception:
            kg_stats = None

        # Latest regression run summary (best-effort; retrieval-only runs are included).
        latest_regression_run: DatasetRegressionRunSummaryOut | None = None
        must_recall_summary: DatasetMustRecallSummaryOut | None = None
        hierarchy_recall_summary: DatasetHierarchyRecallSummaryOut | None = None
        try:
            from app.models.evaluation import RagasRegressionRun

            row = (
                db.query(RagasRegressionRun)
                .filter(RagasRegressionRun.tenant_id == tenant_id, RagasRegressionRun.dataset_id == dataset_id)
                .order_by(RagasRegressionRun.created_at.desc())
                .first()
            )
            if row is not None:
                row_summary = dict(getattr(row, "summary", None) or {})
                latest_regression_run = DatasetRegressionRunSummaryOut(
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
                must_recall_summary = _aggregate_must_recall_summary(
                    latest_regression_summary=row_summary,
                )
                hierarchy_recall_summary = _aggregate_hierarchy_recall_summary(
                    latest_regression_summary=row_summary,
                )
        except Exception:
            latest_regression_run = None
            must_recall_summary = None
            hierarchy_recall_summary = None

        # Governance metrics aggregated from document metadata (best-effort).
        governance_metrics: DatasetGovernanceMetricsOut | None = None
        governance_audit: DatasetGovernanceAuditOut | None = None
        chunk_quality_metrics: DatasetChunkQualityMetricsOut | None = None
        parse_risk_summary: DatasetParseRiskSummaryOut | None = None
        try:
            max_docs = 2000
            _dataset, q = build_dataset_documents_query(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)
            if pipeline_hash_norm:
                active_expr = func.coalesce(
                    DBDocument.doc_metadata["active_pipeline_hash"].as_string(),
                    DBDocument.doc_metadata["pipeline_hash"].as_string(),
                )
                q = q.filter(active_expr == pipeline_hash_norm)

            # Sample the most recently updated docs for responsiveness; report includes a truncation flag.
            rows = q.with_entities(DBDocument.id, DBDocument.doc_metadata).order_by(DBDocument.updated_at.desc()).limit(max_docs + 1).all()
            metas: list[dict] = []
            for row in rows:
                if not isinstance(row, tuple) or len(row) != 2:
                    continue
                doc_id, meta_raw = row
                if not isinstance(meta_raw, dict):
                    continue
                meta = dict(meta_raw)
                if meta.get("document_id") is None:
                    meta["document_id"] = str(doc_id)
                metas.append(meta)
            truncated = len(metas) > max_docs
            if truncated:
                metas = metas[:max_docs]
            governance_metrics = _aggregate_governance_metrics(
                total_documents=int(getattr(profile, "total_documents", 0) or 0),
                metadatas=metas,
                truncated=truncated,
            )
            governance_audit = _aggregate_governance_audit(
                total_documents=int(getattr(profile, "total_documents", 0) or 0),
                metadatas=metas,
                truncated=truncated,
            )
            chunk_quality_metrics = _aggregate_chunk_quality_metrics(
                total_documents=int(getattr(profile, "total_documents", 0) or 0),
                metadatas=metas,
                truncated=truncated,
            )
            try:
                low_threshold = float(getattr(settings, "RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD", 0.35) or 0.35)
            except Exception:
                low_threshold = 0.35
            low_threshold = min(1.0, max(0.0, float(low_threshold)))
            parse_risk_summary = _aggregate_parse_risk_summary(
                total_documents=int(getattr(profile, "total_documents", 0) or 0),
                metadatas=metas,
                truncated=truncated,
                low_threshold=low_threshold,
            )
        except Exception:
            governance_metrics = None
            governance_audit = None
            chunk_quality_metrics = None
            parse_risk_summary = None

        # Optional: latest dataset precheck summary snapshot (best-effort).
        # Precheck runs are "before ingestion" scans over a local folder; we embed the latest
        # completed summary so RAG audit exports can show input distribution signals.
        precheck_summary: dict | None = None
        try:
            from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun

            row = (
                db.query(DBDatasetPrecheckScanRun)
                .filter(
                    DBDatasetPrecheckScanRun.tenant_id == tenant_id,
                    DBDatasetPrecheckScanRun.dataset_id == dataset_id,
                    DBDatasetPrecheckScanRun.status == "completed",
                )
                .order_by(DBDatasetPrecheckScanRun.created_at.desc())
                .first()
            )
            if row is not None:
                raw = getattr(row, "summary", None)
                if isinstance(raw, dict) and raw:
                    precheck_summary = dict(raw)
        except Exception:
            precheck_summary = None

        return DatasetReportOut(
            dataset_id=dataset_id,
            dataset_name=str(getattr(dataset, "name", "") or "") or None,
            pipeline_hash=pipeline_hash_norm,
            generated_at=datetime.now(UTC),
            profile=profile,
            compliance=compliance,
            pipeline_versions=pipeline_versions,
            pipeline_snapshots=pipeline_snapshots,
            connectors=connectors,
            dataset_metadata=dict(getattr(dataset, "dataset_metadata", None) or {}),
            folder_tree=folder_tree,
            governance_metrics=governance_metrics,
            governance_audit=governance_audit,
            chunk_quality_metrics=chunk_quality_metrics,
            parse_risk_summary=parse_risk_summary,
            kg_stats=kg_stats,
            latest_regression_run=latest_regression_run,
            must_recall_summary=must_recall_summary,
            hierarchy_recall_summary=hierarchy_recall_summary,
            precheck_summary=precheck_summary,
        )
