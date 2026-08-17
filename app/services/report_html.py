"""
HTML report rendering (single-file, offline-friendly).

Design goals:
- One self-contained HTML file (no external JS/CSS)
- Objective numbers only (no subjective scoring)
- Optional redaction for sharing (hide dataset id/name/path)
"""

from datetime import datetime
from html import escape
from typing import Any

EMPTY_DATA_DIV = '<div class="empty">暂无数据</div>'
TABLE_TBODY_CLOSE = "</tbody></table>"
REDACTED_TEXT = "[REDACTED]"
BARS_METRIC_TABLE_HEADER = '<table class="bars"><thead><tr><th>Metric</th><th>Value</th><th></th></tr></thead><tbody>'
EMPTY_BRIEF_DIV = '<div class="empty">暂无</div>'
_RETRIEVAL_AUDIT_HTML_METRIC_KEYS = (
    "hit_at_1",
    "hit_at_3",
    "hit_at_5",
    "retrieval_hit_at_1",
    "retrieval_hit_at_3",
    "retrieval_hit_at_5",
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
)


def _fmt_int(n: Any) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return "0"


def _fmt_bytes(n: Any) -> str:
    try:
        b = int(n)
    except Exception:
        b = 0
    if b <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    v = float(b)
    idx = 0
    while v >= 1024.0 and idx < len(units) - 1:
        v /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(v)} {units[idx]}"
    return f"{v:.2f} {units[idx]}"


def _as_items(mapping: Any, *, top: int = 12) -> list[tuple[str, int]]:
    if not isinstance(mapping, dict):
        return []
    items: list[tuple[str, int]] = []
    for k, v in mapping.items():
        key = str(k or "").strip() or "unknown"
        try:
            n = int(v or 0)
        except Exception:
            n = 0
        if n <= 0:
            continue
        items.append((key, n))
    items.sort(key=lambda kv: (-kv[1], kv[0]))
    if top > 0:
        items = items[:top]
    return items


def _render_bar_table(items: list[tuple[str, int]], *, total: int) -> str:
    if not items:
        return EMPTY_DATA_DIV
    total = max(1, int(total or 0))
    rows: list[str] = []
    for k, v in items:
        pct = min(100.0, max(0.0, (float(v) / float(total)) * 100.0))
        rows.append(
            "<tr>"
            f'<td class="k">{escape(str(k))}</td>'
            f'<td class="v">{_fmt_int(v)}</td>'
            f'<td class="bar"><div class="bar-bg"><div class="bar-fill" style="width:{pct:.2f}%"></div></div></td>'
            "</tr>"
        )
    return (
        '<table class="bars">'
        '<thead><tr><th>Key</th><th>Count</th><th style="width:55%">Ratio</th></tr></thead>'
        "<tbody>" + "".join(rows) + TABLE_TBODY_CLOSE
    )


def _render_histogram(bins: Any) -> str:
    if not isinstance(bins, list) or not bins:
        return EMPTY_DATA_DIV
    rows: list[str] = []
    total = 0
    for b in bins:
        if not isinstance(b, dict):
            continue
        label = str(b.get("label") or "").strip()
        try:
            cnt = int(b.get("count") or 0)
        except Exception:
            cnt = 0
        total += max(0, cnt)
        rows.append((label, cnt))

    return _render_bar_table(rows, total=total)


def _fmt_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int) and not isinstance(value, bool):
        return _fmt_int(value)
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _safe_text_list(raw: Any, *, max_items: int = 20, max_len: int = 160) -> list[str]:
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


def _safe_retrieval_audit_payload(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    gates: list[dict[str, Any]] = []
    for gate in raw.get("gates") if isinstance(raw.get("gates"), list) else []:
        if not isinstance(gate, dict):
            continue
        metrics = gate.get("metrics") if isinstance(gate.get("metrics"), dict) else {}
        safe_metrics = {
            key: metrics[key]
            for key in _RETRIEVAL_AUDIT_HTML_METRIC_KEYS
            if isinstance(metrics.get(key), bool)
            or (isinstance(metrics.get(key), (int, float)) and not isinstance(metrics.get(key), bool))
        }
        gates.append(
            {
                "name": str(gate.get("name") or "").strip(),
                "status": str(gate.get("status") or "").strip(),
                "metrics": safe_metrics,
                "failed_conditions": _safe_text_list(gate.get("failed_conditions")),
                "generated_at": str(gate.get("generated_at") or "").strip(),
                "source": str(gate.get("source") or "").strip(),
            }
        )
    failure_categories = raw.get("failure_categories") if isinstance(raw.get("failure_categories"), dict) else {}
    return {
        "status": str(raw.get("status") or "").strip(),
        "plugin_refs": _safe_text_list(raw.get("plugin_refs")),
        "plugin_package_hashes": _safe_text_list(raw.get("plugin_package_hashes")),
        "failure_categories": {
            str(key): int(value or 0) for key, value in failure_categories.items() if str(key or "").strip()
        },
        "kg_recommendation": str(raw.get("kg_recommendation") or "").strip(),
        "recommended_next_action": str(raw.get("recommended_next_action") or "").strip(),
        "gates": gates,
    }


def _report_with_safe_retrieval_audit(report: Any) -> Any:
    if not isinstance(report, dict):
        return report
    out = dict(report)
    safe = _safe_retrieval_audit_payload(report.get("retrieval_audit"))
    if safe is not None:
        out["retrieval_audit"] = safe
    return out


def _render_retrieval_audit_section(report: Any) -> str:
    audit = _safe_retrieval_audit_payload(report.get("retrieval_audit")) if isinstance(report, dict) else None
    if not audit:
        return ""

    status = str(audit.get("status") or "").strip() or "unavailable"
    plugin_refs = _safe_text_list(audit.get("plugin_refs"), max_items=5)
    hashes = [value[:8] for value in _safe_text_list(audit.get("plugin_package_hashes"), max_items=5) if value]
    failure_categories = audit.get("failure_categories") if isinstance(audit.get("failure_categories"), dict) else {}
    kg_recommendation = str(audit.get("kg_recommendation") or "").strip()
    next_action = str(audit.get("recommended_next_action") or "").strip()

    meta_rows = [
        ("status", status),
        ("plugin_refs", ", ".join(plugin_refs)),
        ("plugin_package_hashes", ", ".join(hashes)),
        ("failure_categories", ", ".join(f"{key}:{value}" for key, value in sorted(failure_categories.items()))),
        ("kg_recommendation", kg_recommendation),
        ("next_action", next_action),
    ]
    meta_table = (
        BARS_METRIC_TABLE_HEADER
        + "".join(
            f'<tr><td class="k">{escape(key)}</td><td class="v">{escape(value)}</td><td></td></tr>'
            for key, value in meta_rows
            if value
        )
        + TABLE_TBODY_CLOSE
    )

    metric_rows: list[str] = []
    for gate in audit.get("gates") if isinstance(audit.get("gates"), list) else []:
        if not isinstance(gate, dict):
            continue
        gate_name = str(gate.get("name") or "gate").strip()
        metrics = gate.get("metrics") if isinstance(gate.get("metrics"), dict) else {}
        for key in _RETRIEVAL_AUDIT_HTML_METRIC_KEYS:
            if key not in metrics:
                continue
            metric_rows.append(
                "<tr>"
                f'<td class="k">{escape(f"{gate_name}.{key}")}</td>'
                f'<td class="v">{escape(_fmt_scalar(metrics.get(key)))}</td>'
                "<td></td>"
                "</tr>"
            )
    metric_table = (
        BARS_METRIC_TABLE_HEADER + "".join(metric_rows[:40]) + TABLE_TBODY_CLOSE if metric_rows else EMPTY_DATA_DIV
    )

    return (
        '<div class="section two">'
        "<div><h2>Retrieval Audit</h2>"
        f"{meta_table}"
        "</div>"
        "<div><h2>Retrieval Audit Metrics</h2>"
        f"{metric_table}"
        "</div>"
        "</div>"
    )


_REDACTION_PROFILE_KEYS = {
    "generated_at",
    "total_documents",
    "total_size_bytes",
    "by_status",
    "by_file_type",
    "by_quality_bucket",
    "file_size_histogram",
    "length_percentiles",
    "length_histogram",
    "chunk_count_percentiles",
    "chunk_count_histogram",
    "avg_chunk_chars_percentiles",
    "avg_chunk_chars_histogram",
    "chunk_length_percentiles",
    "chunk_length_histogram",
    "chunk_token_percentiles",
    "chunk_token_histogram",
    "avg_chunk_tokens_percentiles",
    "avg_chunk_tokens_histogram",
    "chunk_coverage_percentiles",
    "chunk_coverage_histogram",
    "chunk_overlap_waste_percentiles",
    "chunk_overlap_waste_histogram",
    "page_number_histogram",
    "parse_quality_histogram",
    "language_mix",
    "pdf_scan",
    "parsing_provenance",
    "pii_hits_total",
    "secrets_hits_total",
}
_REDACTION_COMPLIANCE_KEYS = {"pii_hits_total", "secrets_hits_total", "quarantined_documents", "failed_documents"}
_REDACTION_KG_KEYS = {
    "events",
    "entities",
    "links",
    "events_with_document_id",
    "events_with_chunk_id",
    "events_with_page_ref",
    "links_with_provenance",
    "links_with_page_ref",
    "documents_with_kg_extracted_at",
    "documents_with_kg_events",
    "event_count_from_documents",
    "skipped_chunks_total",
    "skipped_short_chunks_total",
    "failed_chunks_total",
    "retry_chunks_total",
    "entity_types",
    "updated_at",
}
_REDACTION_PRECHECK_KEYS = {
    "generated_at",
    "total_files",
    "total_size_bytes",
    "by_file_type",
    "file_size_histogram",
    "token_histogram",
    "language_mix",
    "pii_hits_total",
    "secrets_hits_total",
    "pdf_scan",
}


def _select_keys(source: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    return {key: source[key] for key in keys if key in source}


def _objective_metrics_only(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        return {
            str(key): scrubbed for key, item in value.items() if (scrubbed := _objective_metrics_only(item)) is not None
        }
    if isinstance(value, list):
        return [scrubbed for item in value if (scrubbed := _objective_metrics_only(item)) is not None]
    return None


def _collect_labeled_counts(items: Any, *, skip_nonpositive: bool = False) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("label") or item.get("key") or "").strip() or "unknown"
        try:
            count = int(item.get("count") or 0)
        except Exception:
            count = 0
        if skip_nonpositive and count <= 0:
            continue
        rows.append((key, count))
    rows.sort(key=lambda kv: (-kv[1], kv[0]))
    return rows


def _render_table_or_empty(header: str, rows: list[str], *, empty: str = EMPTY_DATA_DIV) -> str:
    if not rows:
        return empty
    return header + "".join(rows) + TABLE_TBODY_CLOSE


def _render_metric_value_table(rows: list[tuple[str, Any]]) -> str:
    rendered = [
        f'<tr><td class="k">{escape(str(key))}</td><td class="v">{escape(_fmt_scalar(value))}</td><td></td></tr>'
        for key, value in rows
        if value not in ("", None)
    ]
    return _render_table_or_empty(BARS_METRIC_TABLE_HEADER, rendered)


def _format_generated_at(generated_at: datetime | str | None) -> str:
    return generated_at.isoformat() if isinstance(generated_at, datetime) else (str(generated_at or "") or "")


def _display_identity(*, redact: bool, value: str | None) -> str:
    return REDACTED_TEXT if redact else (value or "")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _int_from(mapping: Any, key: str) -> int:
    try:
        return int(_as_dict(mapping).get(key) or 0)
    except Exception:
        return 0


def _text_from(mapping: Any, key: str) -> str:
    return str(_as_dict(mapping).get(key) or "").strip()


def _percentile_int(mapping: Any, key: str, percentile: str) -> int:
    return _int_from(_as_dict(mapping).get(key), percentile)


def _render_redacted_latest_regression(report: dict[str, Any], safe: dict[str, Any]) -> None:
    regression = report.get("latest_regression_run")
    if not isinstance(regression, dict):
        return
    regression_safe = _select_keys(regression, {"status", "metrics"})
    summary = _objective_metrics_only(regression.get("summary"))
    if isinstance(summary, dict) and summary:
        regression_safe["summary"] = summary
    if regression_safe:
        safe["latest_regression_run"] = regression_safe


def _render_redacted_retrieval_audit(report: dict[str, Any], safe: dict[str, Any]) -> None:
    retrieval_audit = report.get("retrieval_audit")
    if not isinstance(retrieval_audit, dict):
        return
    audit_safe = _select_keys(retrieval_audit, {"status", "failure_categories"})
    if audit_safe:
        safe["retrieval_audit"] = audit_safe


def _render_chunk_targets_table(chunk_targets: Any) -> str:
    rows = [
        "<tr>"
        f'<td class="k">{escape(str(item.get("label") or item.get("key") or "").strip() or "unknown")}</td>'
        f'<td class="v">{escape(str(item.get("status") or "").strip() or "unknown")}</td>'
        f'<td class="v">{escape(str(item.get("message") or "").strip())}</td>'
        f'<td class="v">{escape("; ".join(str(s).strip() for s in _as_list(item.get("suggestions")) if str(s).strip())[:500])}</td>'
        "</tr>"
        for item in _as_list(chunk_targets)
        if isinstance(item, dict)
    ]
    return _render_table_or_empty(
        '<table class="bars"><thead><tr><th>Check</th><th>Status</th><th>Message</th><th>Suggestions</th></tr></thead><tbody>',
        rows,
    )


def _render_recall_risk_table(recall_risk_hints: Any) -> str:
    rows: list[str] = []
    for item in _as_list(recall_risk_hints):
        if not isinstance(item, dict):
            continue
        observed = _as_dict(item.get("observed"))
        observed_str = ", ".join(
            f"{str(key)}={str(value)}" for key, value in sorted(observed.items(), key=lambda kv: str(kv[0] or ""))[:6]
        )[:220]
        rows.append(
            "<tr>"
            f'<td class="k">{escape(str(item.get("label") or item.get("key") or "").strip() or "unknown")}</td>'
            f'<td class="v">{escape(str(item.get("severity") or "").strip() or "warning")}</td>'
            f'<td class="v">{escape(observed_str)}</td>'
            f'<td class="v">{escape(str(item.get("message") or "").strip())}</td>'
            "</tr>"
        )
    return _render_table_or_empty(
        '<table class="bars"><thead><tr><th>Hint</th><th>Severity</th><th>Observed</th><th>Message</th></tr></thead><tbody>',
        rows,
    )


def _collect_version_items(versions: Any) -> list[tuple[str, int]]:
    items: list[tuple[str, int]] = []
    for item in _as_list(versions):
        if not isinstance(item, dict):
            continue
        count = _int_from(item, "documents")
        if count <= 0:
            continue
        items.append((str(item.get("pipeline_hash") or "").strip() or "unknown", count))
    return items


def _render_connector_runs_table(connectors: Any) -> str:
    rows = [
        "<tr>"
        f'<td class="k">{escape(str(item.get("connector_id") or ""))}</td>'
        f'<td class="v">{escape(str(item.get("status") or ""))}</td>'
        f'<td class="v">{escape(str(item.get("created_at") or ""))}</td>'
        "</tr>"
        for item in _as_list(connectors)[:30]
        if isinstance(item, dict)
    ]
    return _render_table_or_empty(
        '<table class="bars"><thead><tr><th>connector_id</th><th>status</th><th>created_at</th></tr></thead><tbody>',
        rows,
    )


def _collect_kg_type_items(raw_types: Any) -> list[tuple[str, int]]:
    items: list[tuple[str, int]] = []
    for item in _as_list(raw_types)[:50]:
        if not isinstance(item, dict):
            continue
        count = _int_from(item, "count")
        if count <= 0:
            continue
        items.append((str(item.get("type") or "").strip() or "unknown", count))
    return items


def _render_kg_top_docs_table(kgd: dict[str, Any], *, redact: bool, include_failures: bool) -> str:
    if redact:
        return EMPTY_DATA_DIV
    rows: list[str] = []
    for item in _as_list(kgd.get("top_documents"))[:10]:
        if not isinstance(item, dict):
            continue
        did = str(item.get("document_id") or "").strip()
        if not did:
            continue
        source = str(item.get("source") or "").strip()
        if include_failures:
            rows.append(
                "<tr>"
                f'<td class="k">{escape(source or did[:8])}</td>'
                f'<td class="v">{_fmt_int(_int_from(item, "event_count"))}</td>'
                f'<td class="v">{_fmt_int(_int_from(item, "skipped_chunks"))}</td>'
                f'<td class="v">{_fmt_int(_int_from(item, "failed_chunks"))}</td>'
                "</tr>"
            )
            continue
        rows.append(
            "<tr>"
            f'<td class=\\"k\\">{escape(source or did[:8])}</td>'
            f'<td class=\\"v\\">{_fmt_int(_int_from(item, "event_count"))}</td>'
            "<td></td>"
            "</tr>"
        )
    header = (
        '<table class="bars"><thead><tr><th>doc</th><th>events</th><th>skipped</th><th>failed</th></tr></thead><tbody>'
        if include_failures
        else '<table class=\\"bars\\"><thead><tr><th>doc</th><th>events</th><th></th></tr></thead><tbody>'
    )
    return _render_table_or_empty(header, rows)


def _render_regression_meta_table(rrd: dict[str, Any], *, include_extended_fields: bool) -> str:
    metrics = ", ".join(str(item) for item in _as_list(rrd.get("metrics")) if str(item or "").strip())[:200]
    rows = [("status", _text_from(rrd, "status")), ("created_at", _text_from(rrd, "created_at"))]
    if include_extended_fields:
        rows.extend(
            [
                ("run_id", _text_from(rrd, "run_id")),
                ("metrics", metrics),
                ("started_at", _text_from(rrd, "started_at")),
            ]
        )
    rows.append(("finished_at", _text_from(rrd, "finished_at")))
    return _render_table_or_empty(
        '<table class="bars"><thead><tr><th>Field</th><th>Value</th><th></th></tr></thead><tbody>',
        [
            f'<tr><td class="k">{escape(str(key))}</td><td class="v">{escape(str(value))}</td><td></td></tr>'
            for key, value in rows
            if value
        ],
    )


def _render_regression_summary_table(rr_summary: Any) -> str:
    rows = [
        f'<tr><td class="k">{escape(str(key))}</td><td class="v">{escape(_fmt_scalar(value))}</td><td></td></tr>'
        for key, value in sorted(_as_dict(rr_summary).items(), key=lambda kv: str(kv[0] or ""))
        if str(key or "").strip()
        and (isinstance(value, bool) or (isinstance(value, (int, float)) and not isinstance(value, bool)))
    ]
    return _render_table_or_empty(BARS_METRIC_TABLE_HEADER, rows)


def _render_rr_slice_table(rr_slices: Any, dim: str, *, redact: bool) -> str:
    if redact and dim == "directory":
        return '<div class="empty">已脱敏：directory 不展示</div>'
    buckets = _as_list(_as_dict(_as_dict(rr_slices).get(dim)).get("buckets"))
    rows: list[str] = []
    for bucket in buckets[:10]:
        if not isinstance(bucket, dict):
            continue
        key = str(bucket.get("key") or "").strip()
        if not key:
            continue
        rows.append(
            "<tr>"
            f'<td class=\\"k\\">{escape(key)}</td>'
            f'<td class=\\"v\\">{_fmt_int(_int_from(bucket, "items"))}</td>'
            f'<td class=\\"v\\">{escape(_fmt_scalar(bucket.get("retrieval_recall")))}</td>'
            f'<td class=\\"v\\">{escape(_fmt_scalar(bucket.get("retrieval_hit_at_20")))}</td>'
            f'<td class=\\"v\\">{escape(_fmt_scalar(bucket.get("retrieval_mrr")))}</td>'
            f'<td class=\\"v\\">{escape(_fmt_scalar(bucket.get("abstain_rate")))}</td>'
            "</tr>"
        )
    return _render_table_or_empty(
        '<table class=\\"bars\\"><thead><tr><th>bucket</th><th>items</th><th>recall</th><th>hit@20</th><th>mrr</th><th>abstain</th></tr></thead><tbody>',
        rows,
        empty='<div class="empty">暂无数据</div>',
    )


def _render_rr_slices_section(
    rr_summary: Any,
    *,
    redact: bool,
    title: str,
    rows: tuple[tuple[str, ...], ...],
) -> str:
    rr_slices = _as_dict(_as_dict(rr_summary).get("retrieval_slices"))
    if not rr_slices:
        return ""
    blocks: list[str] = [f'<div class=\\"section\\"><h2>{title}</h2>']
    for index, dims in enumerate(rows):
        margin = ' style=\\"margin-top:12px\\"' if index > 0 else ""
        blocks.append(f'<div class=\\"two\\"{margin}>')
        for dim in dims:
            blocks.append(f"<div><h2>{dim}</h2>{_render_rr_slice_table(rr_slices, dim, redact=redact)}</div>")
        blocks.append("</div>")
    blocks.append("</div>")
    return "".join(blocks)


def _render_governance_audit_section(governance_audit: Any) -> str:
    ga0 = _as_dict(governance_audit)
    if not ga0:
        return ""
    ga_used_docs = _int_from(ga0, "used_documents")
    ratio = max(0.0, min(1.0, float(ga0.get("char_reduction_ratio") or 0.0)))
    note = ""
    if ga_used_docs > 0:
        truncated = " (truncated)" if bool(ga0.get("truncated") or False) else ""
        note = (
            f'<div class=\\"sub\\" style=\\"margin-top:6px\\">sample: {escape(_fmt_int(ga_used_docs))}{truncated}</div>'
        )
    rows = [
        ("docs_changed", _int_from(ga0, "docs_changed")),
        ("docs_dropped", _int_from(ga0, "docs_dropped")),
        (
            "docs_with_char_stats",
            _int_from(ga0, "docs_with_char_stats") or _int_from(ga0, "docs_with_parsed_content_persisted"),
        ),
        ("docs_with_parsed_content_persisted", _int_from(ga0, "docs_with_parsed_content_persisted")),
        ("parsed_content_truncated_docs", _int_from(ga0, "parsed_content_truncated_docs")),
        ("original_chars_total", _int_from(ga0, "original_chars_total")),
        ("cleaned_chars_total", _int_from(ga0, "cleaned_chars_total")),
        ("char_reduction_ratio", f"{ratio:.2f} ({ratio * 100.0:.1f}%)"),
        ("char_reduction_pct_p50", f"{_fmt_int(_percentile_int(ga0, 'char_reduction_pct_percentiles', 'p50'))}%"),
        ("char_reduction_pct_p90", f"{_fmt_int(_percentile_int(ga0, 'char_reduction_pct_percentiles', 'p90'))}%"),
        ("char_reduction_pct_p99", f"{_fmt_int(_percentile_int(ga0, 'char_reduction_pct_percentiles', 'p99'))}%"),
        ("docs_with_governance_quality", _int_from(ga0, "docs_with_governance_quality")),
        ("density_pct_p50", f"{_fmt_int(_percentile_int(ga0, 'density_pct_percentiles', 'p50'))}%"),
        ("density_pct_p90", f"{_fmt_int(_percentile_int(ga0, 'density_pct_percentiles', 'p90'))}%"),
        ("heading_ratio_pct_p50", f"{_fmt_int(_percentile_int(ga0, 'heading_ratio_pct_percentiles', 'p50'))}%"),
        ("heading_ratio_pct_p90", f"{_fmt_int(_percentile_int(ga0, 'heading_ratio_pct_percentiles', 'p90'))}%"),
        ("paragraphs_dropped_total", _int_from(ga0, "paragraphs_dropped_total")),
        ("references_removed_lines_total", _int_from(ga0, "references_removed_lines_total")),
        ("urls_changed_total", _int_from(ga0, "urls_changed_total")),
        ("boilerplate_removed_sections_total", _int_from(ga0, "boilerplate_removed_sections_total")),
        ("boilerplate_removed_lines_total", _int_from(ga0, "boilerplate_removed_lines_total")),
        ("images_removed_total", _int_from(ga0, "images_removed_total")),
        ("tables_normalized_total", _int_from(ga0, "tables_normalized_total")),
        ("table_rows_changed_total", _int_from(ga0, "table_rows_changed_total")),
        ("code_lines_stripped_total", _int_from(ga0, "code_lines_stripped_total")),
    ]
    return (
        '<div class=\\"section\\"><h2>Governance Audit（治理效果）</h2>'
        + note
        + _render_metric_value_table(rows)
        + "</div>"
    )


def _render_precheck_dir_table(items: Any, *, redact: bool, max_rows: int = 20) -> str:
    if redact:
        return '<div class="empty">已脱敏：目录结构不展示</div>'
    rows: list[str] = []
    for item in _as_list(items)[: max(0, int(max_rows))]:
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f'<td class="k">{escape(str(item.get("path") or "."))}</td>'
            f'<td class="v">{_fmt_int(_int_from(item, "risky_files"))}/{_fmt_int(_int_from(item, "total_files"))}</td>'
            f'<td class="v">{escape(_fmt_bytes(item.get("total_size_bytes") or 0))}</td>'
            "</tr>"
        )
    return _render_table_or_empty(
        '<table class="bars"><thead><tr><th>Directory</th><th>Risky/Total</th><th>Bytes</th></tr></thead><tbody>',
        rows,
    )


def _render_precheck_samples_section(samples: Any) -> str:
    samples_dict = _as_dict(samples)
    if not samples_dict:
        return ""

    def _render_file_list(items: Any, *, max_rows: int = 60) -> str:
        rows = [
            f'<tr><td class="k">{escape(str(item.get("name") or ""))}</td><td class="v">{escape(str(item.get("file_type") or ""))}</td><td class="v">{escape(_fmt_bytes(item.get("file_size")))}</td></tr>'
            for item in _as_list(items)[: max(0, int(max_rows))]
            if isinstance(item, dict)
        ]
        return _render_table_or_empty(
            '<table class="bars"><thead><tr><th>File</th><th>Type</th><th>Size</th></tr></thead><tbody>',
            rows,
            empty=EMPTY_BRIEF_DIV,
        )

    needs_rows = [
        f'<tr><td class="k">{escape(str(key))}</td><td class="v">{_fmt_int(len(value))}</td></tr>'
        for key, value in sorted(_as_dict(samples_dict.get("needs_review")).items(), key=lambda kv: str(kv[0] or ""))
        if isinstance(value, list) and value
    ]
    needs_table = _render_table_or_empty(
        '<table class="bars"><thead><tr><th>Bucket</th><th>Samples</th></tr></thead><tbody>',
        needs_rows,
        empty=EMPTY_BRIEF_DIV,
    )
    return (
        '<div class="section two">'
        "<div><h2>代表性样本（按格式/大小/PDF类型分层）</h2>"
        + _render_file_list(samples_dict.get("representative"), max_rows=60)
        + "</div><div><h2>需复核样本（按问题分桶）</h2>"
        + needs_table
        + "</div></div>"
    )


def _render_precheck_tips_html(
    *,
    summary: dict[str, Any],
    pdf_scanned: int,
    p90: int,
    tok_p90: int,
    pii: list[tuple[str, int]],
    secrets: list[tuple[str, int]],
) -> str:
    findings = _as_list(summary.get("findings"))
    finding_counts = {
        str(item.get("key") or "").strip().lower(): _int_from(item, "count")
        for item in findings
        if isinstance(item, dict) and str(item.get("key") or "").strip()
    }
    tips: list[str] = []
    if pdf_scanned > 0:
        tips.append(
            f"检测到疑似扫描 PDF：{_fmt_int(pdf_scanned)}（建议启用 OCR 解析链路，并优先复核 pdf_unknown/低密度页面）"
        )
    if _int_from(finding_counts, "gibberish_text") > 0:
        tips.append(
            "检测到疑似乱码/编码问题（抽样信号）：建议检查源文件编码、解析器后备策略，并优先启用治理低密度过滤/隔离"
        )
    if _int_from(finding_counts, "empty_text") > 0:
        tips.append("存在“未提取到文本”的文件：若这些文件需要入库，建议调整解析/路由（PDF 走 OCR、二进制先转换）")
    if tok_p90 >= 20_000:
        tips.append(
            f"P90 文本长度较长（~{_fmt_int(tok_p90)} tokens）：建议提高 chunk_size 或使用结构化 chunk_strategy（markdown_header/outline），入库后用 chunk-preview + gate 验证分布"
        )
    elif tok_p90 >= 5_000:
        tips.append(
            f"P90 文本长度偏长（~{_fmt_int(tok_p90)} tokens）：建议检查 chunk_size/overlap，避免 chunk 数过多导致成本/延迟上升"
        )
    elif p90 > 0:
        tips.append(
            "tokens 分布为空（可能未启用文本抽取或文件类型非文本）；如需成本估算，建议开启 enable_text_extract 并重跑预检"
        )
    if pii:
        tips.append("检测到 PII 命中（来自抽样/治理信号）：建议启用治理脱敏/隔离规则（governance_pii_*）并人工复核样本")
    if secrets:
        tips.append(
            "检测到 Secrets/Token 命中（来自抽样/治理信号）：建议启用 secrets 脱敏/隔离（governance_secrets_*）并人工复核样本"
        )
    if not tips:
        tips.append("暂无显著风险信号；建议先用 chunk-preview 小样本调参，再进行小批量入库验证（可回归）")
    return '<div class="notes"><ul>' + "".join(f"<li>{escape(tip)}</li>" for tip in tips) + "</ul></div>"


def _render_precheck_section(precheck_summary: Any, *, redact: bool) -> str:
    pre = _as_dict(precheck_summary)
    if not pre:
        return ""
    pre_total_files = _int_from(pre, "total_files")
    pre_total_bytes = _int_from(pre, "total_size_bytes")
    pdf0 = _as_dict(pre.get("pdf_scan"))
    pre_meta = (
        '<table class="bars">'
        "<thead><tr><th>Field</th><th>Value</th><th></th></tr></thead>"
        "<tbody>"
        f'<tr><td class="k">scan_run_id</td><td class="v">{escape(REDACTED_TEXT if redact else _text_from(pre, "scan_run_id"))}</td><td></td></tr>'
        f'<tr><td class="k">generated_at</td><td class="v">{escape(_text_from(pre, "generated_at"))}</td><td></td></tr>'
        f'<tr><td class="k">total_files</td><td class="v">{_fmt_int(pre_total_files)}</td><td></td></tr>'
        f'<tr><td class="k">total_size</td><td class="v">{escape(_fmt_bytes(pre_total_bytes))}</td><td></td></tr>'
        f'<tr><td class="k">pdf_scan (scanned/text/unknown)</td><td class="v">{_fmt_int(_int_from(pdf0, "scanned"))}/{_fmt_int(_int_from(pdf0, "not_scanned"))}/{_fmt_int(_int_from(pdf0, "unknown"))}</td><td></td></tr>'
        + TABLE_TBODY_CLOSE
    )
    pre_finding_rows = [
        row for row in _collect_labeled_counts(pre.get("findings"), skip_nonpositive=True) if row[1] > 0
    ]
    return (
        '<div class="section">'
        "<h2>Precheck（入库前摸底）</h2>"
        '<div class="two">'
        f"<div><h2>概览</h2>{pre_meta}</div>"
        f"<div><h2>格式分布（Top）</h2>{_render_bar_table(_as_items(pre.get('by_file_type'), top=12), total=max(1, pre_total_files))}</div>"
        "</div>"
        '<div class="two" style="margin-top:12px">'
        f"<div><h2>文件大小分布</h2>{_render_histogram(pre.get('file_size_histogram'))}</div>"
        f"<div><h2>长度分布（tokens）</h2>{_render_histogram(pre.get('token_histogram'))}</div>"
        "</div>"
        '<div class="two" style="margin-top:12px">'
        f"<div><h2>语言分布（抽样）</h2>{_render_bar_table(_as_items(pre.get('language_mix'), top=4), total=max(1, pre_total_files))}</div>"
        f"<div><h2>问题清单（可操作）</h2>{_render_bar_table(pre_finding_rows[:12], total=max(1, pre_total_files))}</div>"
        "</div>"
        '<div class="two" style="margin-top:12px">'
        f"<div><h2>PII 命中（次数）</h2>{_render_bar_table(_as_items(pre.get('pii_hits_total'), top=12), total=max(1, pre_total_files))}</div>"
        f"<div><h2>Secrets/Token 命中（次数）</h2>{_render_bar_table(_as_items(pre.get('secrets_hits_total'), top=12), total=max(1, pre_total_files))}</div>"
        "</div>"
        '<div style="margin-top:12px">'
        f"<h2>目录结构（Top 风险聚集区）</h2>{_render_precheck_dir_table(pre.get('directory_stats'), redact=redact, max_rows=20)}"
        "</div></div>"
    )


def _scrub_report_for_redaction(report: Any) -> dict:
    """
    Best-effort scrubber for `redact=True` HTML exports.

    Goal: prevent leaking dataset identity / paths / internal IDs via the embedded Raw JSON block.
    We keep objective, aggregate metrics that are already rendered elsewhere in the HTML.
    """

    if not isinstance(report, dict):
        return {"redacted": True}

    safe: dict[str, Any] = {"redacted": True}
    if "dataset_name" in report:
        safe["dataset_name"] = REDACTED_TEXT
    if "dataset_id" in report:
        safe["dataset_id"] = REDACTED_TEXT

    for output_key, source_key, keys in (
        ("profile", "profile", _REDACTION_PROFILE_KEYS),
        ("compliance", "compliance", _REDACTION_COMPLIANCE_KEYS),
        ("kg_stats", "kg_stats", _REDACTION_KG_KEYS),
        ("precheck_summary", "precheck_summary", _REDACTION_PRECHECK_KEYS),
    ):
        section = _select_keys(report.get(source_key), keys)
        if section:
            safe[output_key] = section

    for section in ("governance_metrics", "governance_audit", "chunk_quality_metrics"):
        objective = _objective_metrics_only(report.get(section))
        if isinstance(objective, dict) and objective:
            safe[section] = objective

    _render_redacted_latest_regression(report, safe)
    _render_redacted_retrieval_audit(report, safe)
    return safe


def render_dataset_profile_html(
    *,
    title: str,
    dataset_name: str | None,
    dataset_id: str | None,
    generated_at: datetime | str | None,
    summary: dict,
    redact: bool = False,
) -> str:
    name = REDACTED_TEXT if redact else (dataset_name or "")
    dsid = REDACTED_TEXT if redact else (dataset_id or "")
    ts = generated_at.isoformat() if isinstance(generated_at, datetime) else (str(generated_at or "") or "")

    total_docs = int(summary.get("total_documents") or 0)
    total_bytes = int(summary.get("total_size_bytes") or 0)
    p50 = int(
        ((summary.get("length_percentiles") or {}) if isinstance(summary.get("length_percentiles"), dict) else {}).get(
            "p50"
        )
        or 0
    )
    p90 = int(
        ((summary.get("length_percentiles") or {}) if isinstance(summary.get("length_percentiles"), dict) else {}).get(
            "p90"
        )
        or 0
    )
    chunk_p50 = int(
        (
            (summary.get("chunk_count_percentiles") or {})
            if isinstance(summary.get("chunk_count_percentiles"), dict)
            else {}
        ).get("p50")
        or 0
    )
    avg_chunk_p50 = int(
        (
            (summary.get("avg_chunk_chars_percentiles") or {})
            if isinstance(summary.get("avg_chunk_chars_percentiles"), dict)
            else {}
        ).get("p50")
        or 0
    )
    chunk_len_p50 = int(
        (
            (summary.get("chunk_length_percentiles") or {})
            if isinstance(summary.get("chunk_length_percentiles"), dict)
            else {}
        ).get("p50")
        or 0
    )
    chunk_tok_p50 = int(
        (
            (summary.get("chunk_token_percentiles") or {})
            if isinstance(summary.get("chunk_token_percentiles"), dict)
            else {}
        ).get("p50")
        or 0
    )
    avg_chunk_tok_p50 = int(
        (
            (summary.get("avg_chunk_tokens_percentiles") or {})
            if isinstance(summary.get("avg_chunk_tokens_percentiles"), dict)
            else {}
        ).get("p50")
        or 0
    )
    cov_p50 = int(
        (
            (summary.get("chunk_coverage_percentiles") or {})
            if isinstance(summary.get("chunk_coverage_percentiles"), dict)
            else {}
        ).get("p50")
        or 0
    )
    waste_p50 = int(
        (
            (summary.get("chunk_overlap_waste_percentiles") or {})
            if isinstance(summary.get("chunk_overlap_waste_percentiles"), dict)
            else {}
        ).get("p50")
        or 0
    )

    pdf = summary.get("pdf_scan") if isinstance(summary.get("pdf_scan"), dict) else {}
    pdf_scanned = int(pdf.get("scanned") or 0)
    pdf_text = int(pdf.get("not_scanned") or 0)
    pdf_unknown = int(pdf.get("unknown") or 0)

    by_type = _as_items(summary.get("by_file_type"), top=12)
    by_status = _as_items(summary.get("by_status"), top=12)
    lang = _as_items(summary.get("language_mix"), top=12)
    dirs = [] if redact else _as_items(summary.get("by_directory"), top=12)
    qual = _as_items(summary.get("by_quality_bucket"), top=12)
    pii = _as_items(summary.get("pii_hits_total"), top=12)
    secrets = _as_items(summary.get("secrets_hits_total"), top=12)

    findings = summary.get("findings") if isinstance(summary.get("findings"), list) else []
    finding_rows: list[tuple[str, int]] = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        key = str(f.get("label") or f.get("key") or "").strip() or "unknown"
        try:
            cnt = int(f.get("count") or 0)
        except Exception:
            cnt = 0
        finding_rows.append((key, cnt))
    finding_rows.sort(key=lambda kv: (-kv[1], kv[0]))

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #0b1020;
      --card: rgba(255,255,255,.06);
      --muted: rgba(255,255,255,.65);
      --text: rgba(255,255,255,.92);
      --border: rgba(255,255,255,.10);
      --accent: #38bdf8;
      --accent2: #22c55e;
      --warn: #f59e0b;
      --err: #fb7185;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      --sans: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji", "Segoe UI Emoji";
    }}
    body {{ margin: 0; background: radial-gradient(1200px 800px at 10% 10%, rgba(56,189,248,.16), transparent), var(--bg); color: var(--text); font-family: var(--sans); }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 28px 18px 40px; }}
    .title {{ font-size: 22px; font-weight: 800; letter-spacing: .2px; }}
    .sub {{ margin-top: 6px; color: var(--muted); font-size: 13px; }}
    .grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-top: 16px; }}
    .card {{ border: 1px solid var(--border); border-radius: 14px; background: var(--card); padding: 12px 12px; }}
    .kpi-label {{ color: var(--muted); font-size: 12px; }}
    .kpi-value {{ font-family: var(--mono); font-weight: 800; font-size: 18px; margin-top: 6px; }}
    .section {{ margin-top: 16px; border: 1px solid var(--border); border-radius: 14px; background: rgba(0,0,0,.12); padding: 14px 14px; }}
    .section h2 {{ margin: 0 0 10px; font-size: 14px; letter-spacing: .2px; }}
    .two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .empty {{ color: var(--muted); font-size: 13px; padding: 18px 0; text-align: center; }}
    table.bars {{ width: 100%; border-collapse: collapse; }}
    table.bars th {{ text-align: left; font-size: 12px; color: var(--muted); font-family: var(--mono); padding: 8px 6px; border-bottom: 1px solid var(--border); }}
    table.bars td {{ padding: 7px 6px; border-bottom: 1px solid rgba(255,255,255,.06); vertical-align: middle; }}
    table.bars td.k {{ font-family: var(--mono); font-size: 12px; color: var(--text); max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    table.bars td.v {{ font-family: var(--mono); font-size: 12px; color: var(--muted); width: 90px; }}
    .bar-bg {{ height: 10px; border-radius: 99px; background: rgba(255,255,255,.08); overflow: hidden; }}
    .bar-fill {{ height: 10px; border-radius: 99px; background: linear-gradient(90deg, var(--accent), rgba(34,197,94,.9)); }}
    .footer {{ margin-top: 18px; color: var(--muted); font-size: 12px; }}
    @media (max-width: 980px) {{ .grid {{ grid-template-columns: repeat(2, 1fr); }} .two {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="title">{escape(title)}</div>
    <div class="sub">dataset: <span style="font-family:var(--mono)">{escape(name)}</span> · id: <span style="font-family:var(--mono)">{escape(dsid)}</span> · generated_at: <span style="font-family:var(--mono)">{escape(ts)}</span></div>

    <div class="grid">
      <div class="card"><div class="kpi-label">文档总数</div><div class="kpi-value">{_fmt_int(total_docs)}</div></div>
      <div class="card"><div class="kpi-label">总大小</div><div class="kpi-value">{escape(_fmt_bytes(total_bytes))}</div></div>
      <div class="card"><div class="kpi-label">P50 长度（chars）</div><div class="kpi-value">{_fmt_int(p50)}</div></div>
      <div class="card"><div class="kpi-label">P90 长度（chars）</div><div class="kpi-value">{_fmt_int(p90)}</div></div>
      <div class="card"><div class="kpi-label">PDF 扫描/文本/未知</div><div class="kpi-value">{_fmt_int(pdf_scanned)}/{_fmt_int(pdf_text)}/{_fmt_int(pdf_unknown)}</div></div>
      <div class="card"><div class="kpi-label">P50 chunks/doc</div><div class="kpi-value">{_fmt_int(chunk_p50)}</div></div>
      <div class="card"><div class="kpi-label">P50 avg chunk（chars）</div><div class="kpi-value">{_fmt_int(avg_chunk_p50)}</div></div>
      <div class="card"><div class="kpi-label">P50 chunk len（chars）</div><div class="kpi-value">{_fmt_int(chunk_len_p50)}</div></div>
      <div class="card"><div class="kpi-label">P50 avg chunk（tokens）</div><div class="kpi-value">{_fmt_int(avg_chunk_tok_p50)}</div></div>
      <div class="card"><div class="kpi-label">P50 chunk len（tokens）</div><div class="kpi-value">{_fmt_int(chunk_tok_p50)}</div></div>
      <div class="card"><div class="kpi-label">P50 coverage（%）</div><div class="kpi-value">{_fmt_int(cov_p50)}%</div></div>
      <div class="card"><div class="kpi-label">P50 overlap waste（%）</div><div class="kpi-value">{_fmt_int(waste_p50)}%</div></div>
    </div>

    <div class="section">
      <h2>格式分布（Top）</h2>
      {_render_bar_table(by_type, total=total_docs)}
    </div>

    <div class="section two">
      <div>
        <h2>状态分布</h2>
        {_render_bar_table(by_status, total=total_docs)}
      </div>
      <div>
        <h2>问题清单（可操作）</h2>
        {_render_bar_table(finding_rows, total=max(1, total_docs))}
      </div>
    </div>

    <div class="section two">
      <div>
        <h2>长度分布（chars）</h2>
        {_render_histogram(summary.get("length_histogram"))}
      </div>
      <div>
        <h2>文件大小分布</h2>
        {_render_histogram(summary.get("file_size_histogram"))}
      </div>
    </div>

    <div class="section two">
      <div>
        <h2>页数分布</h2>
        {_render_histogram(summary.get("page_number_histogram"))}
      </div>
      <div>
        <h2>解析质量分布</h2>
        {_render_histogram(summary.get("parse_quality_histogram"))}
      </div>
    </div>

    <div class="section two">
      <div>
        <h2>语言分布</h2>
        {_render_bar_table(lang, total=max(1, total_docs))}
      </div>
      <div>
        <h2>Chunk 数分布（每文档）</h2>
        {_render_histogram(summary.get("chunk_count_histogram"))}
      </div>
    </div>

    <div class="section two">
      <div>
        <h2>目录分布（Top-level）</h2>
        {_render_bar_table(dirs, total=max(1, total_docs))}
      </div>
      <div>
        <h2>质量桶分布</h2>
        {_render_bar_table(qual, total=max(1, total_docs))}
      </div>
    </div>

    <div class="section">
      <h2>Chunk 长度分布（chars，chunk-level）</h2>
      {_render_histogram(summary.get("chunk_length_histogram"))}
    </div>

    <div class="section">
      <h2>平均 Chunk 长度分布（chars/chunk，每文档）</h2>
      {_render_histogram(summary.get("avg_chunk_chars_histogram"))}
    </div>

    <div class="section">
      <h2>Chunk 长度分布（tokens，chunk-level）</h2>
      {_render_histogram(summary.get("chunk_token_histogram"))}
    </div>

    <div class="section">
      <h2>平均 Chunk 长度分布（tokens/chunk，每文档）</h2>
      {_render_histogram(summary.get("avg_chunk_tokens_histogram"))}
    </div>

    <div class="section two">
      <div>
        <h2>Chunk coverage 分布（%）</h2>
        {_render_histogram(summary.get("chunk_coverage_histogram"))}
      </div>
      <div>
        <h2>Overlap waste 分布（%）</h2>
        {_render_histogram(summary.get("chunk_overlap_waste_histogram"))}
      </div>
    </div>

    <div class="section two">
      <div>
        <h2>PII 命中（次数）</h2>
        {_render_bar_table(pii, total=max(1, sum(v for _, v in pii) if pii else 1))}
      </div>
      <div>
        <h2>Secrets/Token 命中（次数）</h2>
        {_render_bar_table(secrets, total=max(1, sum(v for _, v in secrets) if secrets else 1))}
      </div>
    </div>

    <div class="footer">
      <div>说明：报告仅展示客观统计（不做主观评分）。PII/Secrets 为抽样/治理阶段统计，需人工复核。</div>
    </div>
  </div>
</body>
</html>
"""
    return html


def render_dataset_report_html(
    *,
    title: str,
    dataset_name: str | None,
    dataset_id: str | None,
    generated_at: datetime | str | None,
    report: dict,
    redact: bool = False,
) -> str:
    """
    Render a dataset report bundle as a single-file HTML.

    This intentionally stays simple (offline-friendly) and includes the raw JSON
    payload for auditing/sharing.
    """
    import json

    if redact:
        report = _scrub_report_for_redaction(report)
    report_dict = report if isinstance(report, dict) else {}
    name = _display_identity(redact=redact, value=dataset_name)
    dsid = _display_identity(redact=redact, value=dataset_id)
    ts = _format_generated_at(generated_at)

    prof = _as_dict(report_dict.get("profile"))
    total_docs = _int_from(prof, "total_documents")
    total_bytes = _int_from(prof, "total_size_bytes")
    by_status = _as_items(prof.get("by_status"), top=12)
    by_type = _as_items(prof.get("by_file_type"), top=12)
    finding_rows = _collect_labeled_counts(prof.get("findings"), skip_nonpositive=True)

    prov = _as_dict(prof.get("parsing_provenance"))
    prov_docs = _int_from(prov, "docs_with_provenance")
    prov_by_backend = _as_items(prov.get("by_resolved_backend"), top=12)
    prov_meta_table = _render_metric_value_table(
        [
            ("docs_with_provenance", prov_docs),
            ("fallback_docs", _int_from(prov, "fallback_docs")),
            ("p50_elapsed_ms", _percentile_int(prov, "elapsed_ms_percentiles", "p50")),
            ("p90_elapsed_ms", _percentile_int(prov, "elapsed_ms_percentiles", "p90")),
        ]
    )
    chunk_targets_table = _render_chunk_targets_table(prof.get("chunk_targets"))
    recall_risk_table = _render_recall_risk_table(prof.get("recall_risk_hints"))

    compd = _as_dict(report_dict.get("compliance"))
    quarantined = _int_from(compd, "quarantined_documents")
    failed = _int_from(compd, "failed_documents")

    version_items = _collect_version_items(report_dict.get("pipeline_versions"))
    connector_runs_table = _render_connector_runs_table(report_dict.get("connectors"))

    cqmd = _as_dict(report_dict.get("chunk_quality_metrics"))
    gate_grades = _as_items(cqmd.get("gate_grade_docs"), top=12)
    coverage_low = _int_from(cqmd, "coverage_low_documents")
    overlap_high = _int_from(cqmd, "overlap_waste_high_documents")
    tokens_missing = _int_from(cqmd, "token_stats_missing_documents")

    kgd = _as_dict(report_dict.get("kg_stats"))
    kg_events = _int_from(kgd, "events")
    kg_entities = _int_from(kgd, "entities")
    kg_links = _int_from(kgd, "links")
    kg_events_with_chunk = _int_from(kgd, "events_with_chunk_id")
    kg_events_with_page = _int_from(kgd, "events_with_page_ref")
    kg_links_with_prov = _int_from(kgd, "links_with_provenance")
    kg_links_with_page = _int_from(kgd, "links_with_page_ref")
    kg_docs_extracted = _int_from(kgd, "documents_with_kg_extracted_at")
    kg_docs_with_events = _int_from(kgd, "documents_with_kg_events")
    kg_event_count_from_docs = _int_from(kgd, "event_count_from_documents")
    kg_skipped_chunks = _int_from(kgd, "skipped_chunks_total")
    kg_skipped_short = _int_from(kgd, "skipped_short_chunks_total")
    kg_failed_chunks = _int_from(kgd, "failed_chunks_total")
    kg_retry_chunks = _int_from(kgd, "retry_chunks_total")
    kg_updated_at = _text_from(kgd, "updated_at")
    kg_type_items = _collect_kg_type_items(kgd.get("entity_types"))
    kg_top_docs_table = _render_kg_top_docs_table(kgd, redact=redact, include_failures=True)

    rrd = _as_dict(report_dict.get("latest_regression_run"))
    rr_summary = _as_dict(rrd.get("summary"))
    rr_meta_table = _render_regression_meta_table(rrd, include_extended_fields=True)
    rr_summary_table = _render_regression_summary_table(rr_summary)
    rr_slices_section = _render_rr_slices_section(
        rr_summary,
        redact=redact,
        title="Retrieval Slices",
        rows=(("file_type", "language"), ("hit_type", "quality"), ("pipeline_hash", "directory")),
    )

    retrieval_audit_section = _render_retrieval_audit_section(report_dict)
    raw_report = _report_with_safe_retrieval_audit(report_dict)
    raw_payload = _scrub_report_for_redaction(raw_report) if redact else raw_report
    raw_json = json.dumps(raw_payload, ensure_ascii=False, indent=2)

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #0b1020;
      --card: rgba(255,255,255,.06);
      --muted: rgba(255,255,255,.65);
      --text: rgba(255,255,255,.92);
      --border: rgba(255,255,255,.10);
      --accent: #38bdf8;
      --accent2: #22c55e;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      --sans: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
    }}
    body {{ margin: 0; background: radial-gradient(1200px 800px at 10% 10%, rgba(56,189,248,.16), transparent), var(--bg); color: var(--text); font-family: var(--sans); }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 28px 18px 40px; }}
    .title {{ font-size: 22px; font-weight: 800; letter-spacing: .2px; }}
    .sub {{ margin-top: 6px; color: var(--muted); font-size: 13px; }}
    .grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-top: 16px; }}
    .card {{ border: 1px solid var(--border); border-radius: 14px; background: var(--card); padding: 12px 12px; }}
    .kpi-label {{ color: var(--muted); font-size: 12px; }}
    .kpi-value {{ font-family: var(--mono); font-weight: 800; font-size: 18px; margin-top: 6px; }}
    .section {{ margin-top: 16px; border: 1px solid var(--border); border-radius: 14px; background: rgba(0,0,0,.12); padding: 14px 14px; }}
    .section h2 {{ margin: 0 0 10px; font-size: 14px; letter-spacing: .2px; }}
    .two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .empty {{ color: var(--muted); font-size: 13px; padding: 18px 0; text-align: center; }}
    table.bars {{ width: 100%; border-collapse: collapse; }}
    table.bars th {{ text-align: left; font-size: 12px; color: var(--muted); font-family: var(--mono); padding: 8px 6px; border-bottom: 1px solid var(--border); }}
    table.bars td {{ padding: 7px 6px; border-bottom: 1px solid rgba(255,255,255,.06); vertical-align: middle; }}
    table.bars td.k {{ font-family: var(--mono); font-size: 12px; color: var(--text); max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    table.bars td.v {{ font-family: var(--mono); font-size: 12px; color: var(--muted); width: 160px; }}
    .bar-bg {{ height: 10px; border-radius: 99px; background: rgba(255,255,255,.08); overflow: hidden; }}
    .bar-fill {{ height: 10px; border-radius: 99px; background: linear-gradient(90deg, var(--accent), rgba(34,197,94,.9)); }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: rgba(0,0,0,.22); padding: 12px; border: 1px solid rgba(255,255,255,.08); border-radius: 12px; font-family: var(--mono); font-size: 12px; color: var(--text); }}
    .footer {{ margin-top: 18px; color: var(--muted); font-size: 12px; }}
    @media (max-width: 980px) {{ .grid {{ grid-template-columns: repeat(2, 1fr); }} .two {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="title">{escape(title)}</div>
    <div class="sub">dataset: <span style="font-family:var(--mono)">{escape(name)}</span> · id: <span style="font-family:var(--mono)">{escape(dsid)}</span> · generated_at: <span style="font-family:var(--mono)">{escape(ts)}</span></div>

    <div class="grid">
      <div class="card"><div class="kpi-label">文档总数</div><div class="kpi-value">{_fmt_int(total_docs)}</div></div>
      <div class="card"><div class="kpi-label">总大小</div><div class="kpi-value">{escape(_fmt_bytes(total_bytes))}</div></div>
      <div class="card"><div class="kpi-label">隔离（Quarantine）</div><div class="kpi-value">{_fmt_int(quarantined)}</div></div>
      <div class="card"><div class="kpi-label">失败（Failed）</div><div class="kpi-value">{_fmt_int(failed)}</div></div>
      <div class="card"><div class="kpi-label">Pipeline Filter</div><div class="kpi-value">{escape(str(report.get("pipeline_hash") or "all"))}</div></div>
    </div>

\t    <div class="section two">
\t      <div>
\t        <h2>状态分布</h2>
\t        {_render_bar_table(by_status, total=max(1, total_docs))}
\t      </div>
\t      <div>
\t        <h2>格式分布（Top）</h2>
\t        {_render_bar_table(by_type, total=max(1, total_docs))}
\t      </div>
\t    </div>

\t    <div class="section two">
\t      <div>
\t        <h2>问题清单（可操作）</h2>
\t        {_render_bar_table(finding_rows, total=max(1, total_docs))}
\t      </div>
\t      <div>
\t        <h2>Parsing / Routing（Docs）</h2>
\t        {_render_bar_table(prov_by_backend, total=max(1, prov_docs))}
\t        <div style="margin-top:10px">{prov_meta_table}</div>
\t      </div>
\t    </div>

\t    <div class="section two">
\t      <div>
\t        <h2>Chunk Quality Gate（文档数）</h2>
\t        {_render_bar_table(gate_grades, total=max(1, total_docs))}
\t      </div>
\t      <div>
\t        <h2>Chunk 风险计数（best-effort）</h2>
\t        {_render_bar_table([("coverage_low", coverage_low), ("overlap_waste_high", overlap_high), ("token_stats_missing", tokens_missing)], total=max(1, total_docs))}
\t      </div>
\t    </div>

\t    <div class="section">
\t      <h2>Chunk Targets（分布目标检查）</h2>
\t      {chunk_targets_table}
\t    </div>

\t    <div class="section">
\t      <h2>召回风险摘要（Recall Risk Hints）</h2>
\t      {recall_risk_table}
\t    </div>

\t    <div class="section two">
\t      <div>
\t        <h2>Knowledge Graph（KG）</h2>
\t        <table class="bars">
\t          <thead><tr><th>Metric</th><th>Value</th><th></th></tr></thead>
          <tbody>
            <tr><td class="k">events</td><td class="v">{_fmt_int(kg_events)}</td><td></td></tr>
            <tr><td class="k">entities</td><td class="v">{_fmt_int(kg_entities)}</td><td></td></tr>
            <tr><td class="k">links</td><td class="v">{_fmt_int(kg_links)}</td><td></td></tr>
            <tr><td class="k">events_with_chunk_id</td><td class="v">{_fmt_int(kg_events_with_chunk)}</td><td></td></tr>
            <tr><td class="k">events_with_page_ref</td><td class="v">{_fmt_int(kg_events_with_page)}</td><td></td></tr>
            <tr><td class="k">links_with_provenance</td><td class="v">{_fmt_int(kg_links_with_prov)}</td><td></td></tr>
            <tr><td class="k">links_with_page_ref</td><td class="v">{_fmt_int(kg_links_with_page)}</td><td></td></tr>
            <tr><td class="k">documents_with_kg_extracted_at</td><td class="v">{_fmt_int(kg_docs_extracted)}</td><td></td></tr>
            <tr><td class="k">documents_with_kg_events</td><td class="v">{_fmt_int(kg_docs_with_events)}</td><td></td></tr>
            <tr><td class="k">event_count_from_documents</td><td class="v">{_fmt_int(kg_event_count_from_docs)}</td><td></td></tr>
            <tr><td class="k">skipped_chunks_total</td><td class="v">{_fmt_int(kg_skipped_chunks)}</td><td></td></tr>
            <tr><td class="k">skipped_short_chunks_total</td><td class="v">{_fmt_int(kg_skipped_short)}</td><td></td></tr>
            <tr><td class="k">failed_chunks_total</td><td class="v">{_fmt_int(kg_failed_chunks)}</td><td></td></tr>
            <tr><td class="k">retry_chunks_total</td><td class="v">{_fmt_int(kg_retry_chunks)}</td><td></td></tr>
            <tr><td class="k">updated_at</td><td class="v">{escape(kg_updated_at or "")}</td><td></td></tr>
          </tbody>
        </table>
      </div>
      <div>
        <h2>实体类型（Top）</h2>
        {_render_bar_table(kg_type_items, total=max(1, sum(v for _, v in kg_type_items) if kg_type_items else 1))}
      </div>
    </div>

    <div class="section">
      <h2>KG Drilldown（Top Documents）</h2>
      {kg_top_docs_table}
    </div>

    <div class="section two">
      <div>
        <h2>评估（Regression Run）</h2>
        {rr_meta_table}
      </div>
      <div>
        <h2>评估 Summary</h2>
        {rr_summary_table}
      </div>
    </div>

    {retrieval_audit_section}

    {rr_slices_section}

    <div class="section">
      <h2>Pipeline 版本分布</h2>
      {_render_bar_table(version_items, total=max(1, total_docs))}
    </div>

    <div class="section">
      <h2>最近 Connector Runs</h2>
      {connector_runs_table}
    </div>

    <div class="section">
      <h2>Raw JSON（用于审计/分享）</h2>
      <pre>{escape(raw_json)}</pre>
    </div>

    <div class="footer">
      <div>说明：报告聚合现有画像/治理/入库指标，以可分享的 HTML + JSON 输出为目标。</div>
    </div>
  </div>
</body>
</html>
"""
    return html


def render_rag_audit_html(
    *,
    title: str,
    dataset_name: str | None,
    dataset_id: str | None,
    generated_at: datetime | str | None,
    report: dict,
    redact: bool = False,
) -> str:
    """
    Render a one-page RAG audit HTML bundle.

    Goal:
    - Merge profile + governance + chunk + KG + eval into a single offline-friendly report.
    - Keep it objective: show numbers and distributions; avoid subjective scoring.
    """
    import json

    if redact:
        report = _scrub_report_for_redaction(report)
    report_dict = report if isinstance(report, dict) else {}
    name = _display_identity(redact=redact, value=dataset_name)
    dsid = _display_identity(redact=redact, value=dataset_id)
    ts = _format_generated_at(generated_at)

    prof = _as_dict(report_dict.get("profile"))
    total_docs = _int_from(prof, "total_documents")
    total_bytes = _int_from(prof, "total_size_bytes")
    by_status = _as_items(prof.get("by_status"), top=12)
    by_type = _as_items(prof.get("by_file_type"), top=12)
    p50 = _percentile_int(prof, "length_percentiles", "p50")
    p90 = _percentile_int(prof, "length_percentiles", "p90")
    chunk_tok_p50 = _percentile_int(prof, "chunk_token_percentiles", "p50")
    cov_p50 = _percentile_int(prof, "chunk_coverage_percentiles", "p50")

    compd = _as_dict(report_dict.get("compliance"))
    quarantined = _int_from(compd, "quarantined_documents")
    failed = _int_from(compd, "failed_documents")

    govd = _as_dict(report_dict.get("governance_metrics"))
    drop_reasons = _as_items(govd.get("drop_reasons_total"), top=12)
    rule_packs = _as_items(govd.get("rule_packs_docs"), top=12)
    governance_audit_section = _render_governance_audit_section(report_dict.get("governance_audit"))

    cqmd = _as_dict(report_dict.get("chunk_quality_metrics"))
    gate_grades = _as_items(cqmd.get("gate_grade_docs"), top=12)
    coverage_low = _int_from(cqmd, "coverage_low_documents")
    overlap_high = _int_from(cqmd, "overlap_waste_high_documents")
    tokens_missing = _int_from(cqmd, "token_stats_missing_documents")

    precheck_section = _render_precheck_section(report_dict.get("precheck_summary"), redact=redact)

    kgd = _as_dict(report_dict.get("kg_stats"))
    kg_events = _int_from(kgd, "events")
    kg_entities = _int_from(kgd, "entities")
    kg_links = _int_from(kgd, "links")
    kg_events_with_chunk = _int_from(kgd, "events_with_chunk_id")
    kg_events_with_page = _int_from(kgd, "events_with_page_ref")
    kg_links_with_prov = _int_from(kgd, "links_with_provenance")
    kg_links_with_page = _int_from(kgd, "links_with_page_ref")
    kg_docs_extracted = _int_from(kgd, "documents_with_kg_extracted_at")
    kg_docs_with_events = _int_from(kgd, "documents_with_kg_events")
    kg_event_count_from_docs = _int_from(kgd, "event_count_from_documents")
    kg_skipped_chunks = _int_from(kgd, "skipped_chunks_total")
    kg_skipped_short = _int_from(kgd, "skipped_short_chunks_total")
    kg_failed_chunks = _int_from(kgd, "failed_chunks_total")
    kg_retry_chunks = _int_from(kgd, "retry_chunks_total")
    kg_updated_at = _text_from(kgd, "updated_at")
    kg_types = _collect_kg_type_items(kgd.get("entity_types"))
    kg_top_docs_table = _render_kg_top_docs_table(kgd, redact=redact, include_failures=False)

    rrd = _as_dict(report_dict.get("latest_regression_run"))
    rr_status = _text_from(rrd, "status")
    rr_created_at = _text_from(rrd, "created_at")
    rr_finished_at = _text_from(rrd, "finished_at")
    rr_summary = _as_dict(rrd.get("summary"))
    rr_summary_table = _render_regression_summary_table(rr_summary)
    rr_slices_section = _render_rr_slices_section(
        rr_summary,
        redact=redact,
        title="Retrieval Slices（file_type / language / directory）",
        rows=(("file_type", "language"), ("directory",)),
    )

    retrieval_audit_section = _render_retrieval_audit_section(report_dict)
    raw_report = _report_with_safe_retrieval_audit(report_dict)
    raw_payload = _scrub_report_for_redaction(raw_report) if redact else raw_report
    raw_json = json.dumps(raw_payload, ensure_ascii=False, indent=2)

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #0b1020;
      --card: rgba(255,255,255,.06);
      --muted: rgba(255,255,255,.65);
      --text: rgba(255,255,255,.92);
      --border: rgba(255,255,255,.10);
      --accent: #38bdf8;
      --accent2: #22c55e;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      --sans: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
    }}
    body {{ margin: 0; background: radial-gradient(1200px 800px at 10% 10%, rgba(34,197,94,.12), transparent), var(--bg); color: var(--text); font-family: var(--sans); }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 28px 18px 40px; }}
    .title {{ font-size: 22px; font-weight: 800; letter-spacing: .2px; }}
    .sub {{ margin-top: 6px; color: var(--muted); font-size: 13px; }}
    .grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-top: 16px; }}
    .card {{ border: 1px solid var(--border); border-radius: 14px; background: var(--card); padding: 12px 12px; }}
    .kpi-label {{ color: var(--muted); font-size: 12px; }}
    .kpi-value {{ font-family: var(--mono); font-weight: 800; font-size: 18px; margin-top: 6px; }}
    .section {{ margin-top: 16px; border: 1px solid var(--border); border-radius: 14px; background: rgba(0,0,0,.12); padding: 14px 14px; }}
    .section h2 {{ margin: 0 0 10px; font-size: 14px; letter-spacing: .2px; }}
    .two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .empty {{ color: var(--muted); font-size: 13px; padding: 18px 0; text-align: center; }}
    table.bars {{ width: 100%; border-collapse: collapse; }}
    table.bars th {{ text-align: left; font-size: 12px; color: var(--muted); font-family: var(--mono); padding: 8px 6px; border-bottom: 1px solid var(--border); }}
    table.bars td {{ padding: 7px 6px; border-bottom: 1px solid rgba(255,255,255,.06); vertical-align: middle; }}
    table.bars td.k {{ font-family: var(--mono); font-size: 12px; color: var(--text); max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    table.bars td.v {{ font-family: var(--mono); font-size: 12px; color: var(--muted); width: 160px; }}
    .bar-bg {{ height: 10px; border-radius: 99px; background: rgba(255,255,255,.08); overflow: hidden; }}
    .bar-fill {{ height: 10px; border-radius: 99px; background: linear-gradient(90deg, var(--accent), rgba(34,197,94,.9)); }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: rgba(0,0,0,.22); padding: 12px; border: 1px solid rgba(255,255,255,.08); border-radius: 12px; font-family: var(--mono); font-size: 12px; color: var(--text); }}
    .footer {{ margin-top: 18px; color: var(--muted); font-size: 12px; }}
    @media (max-width: 980px) {{ .grid {{ grid-template-columns: repeat(2, 1fr); }} .two {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="title">{escape(title)}</div>
    <div class="sub">dataset: <span style="font-family:var(--mono)">{escape(name)}</span> · id: <span style="font-family:var(--mono)">{escape(dsid)}</span> · generated_at: <span style="font-family:var(--mono)">{escape(ts)}</span></div>

    <div class="grid">
      <div class="card"><div class="kpi-label">文档总数</div><div class="kpi-value">{_fmt_int(total_docs)}</div></div>
      <div class="card"><div class="kpi-label">总大小</div><div class="kpi-value">{escape(_fmt_bytes(total_bytes))}</div></div>
      <div class="card"><div class="kpi-label">隔离（Quarantine）</div><div class="kpi-value">{_fmt_int(quarantined)}</div></div>
      <div class="card"><div class="kpi-label">失败（Failed）</div><div class="kpi-value">{_fmt_int(failed)}</div></div>
      <div class="card"><div class="kpi-label">P50 长度（chars）</div><div class="kpi-value">{_fmt_int(p50)}</div></div>
      <div class="card"><div class="kpi-label">P90 长度（chars）</div><div class="kpi-value">{_fmt_int(p90)}</div></div>
      <div class="card"><div class="kpi-label">P50 chunk len（tokens）</div><div class="kpi-value">{_fmt_int(chunk_tok_p50)}</div></div>
      <div class="card"><div class="kpi-label">P50 coverage（%）</div><div class="kpi-value">{_fmt_int(cov_p50)}%</div></div>
    </div>

\t    <div class="section two">
\t      <div>
\t        <h2>状态分布</h2>
\t        {_render_bar_table(by_status, total=max(1, total_docs))}
\t      </div>
\t      <div>
\t        <h2>格式分布（Top）</h2>
\t        {_render_bar_table(by_type, total=max(1, total_docs))}
\t      </div>
\t    </div>

\t\t    <div class="section two">
\t\t      <div>
\t\t        <h2>长度分布（chars）</h2>
\t\t        {_render_histogram(prof.get("length_histogram"))}
\t      </div>
      <div>
        <h2>文件大小分布</h2>
        {_render_histogram(prof.get("file_size_histogram"))}
      </div>
    </div>

    {precheck_section}

    <div class="section two">
      <div>
        <h2>Chunk Quality Gate（文档数）</h2>
        {_render_bar_table(gate_grades, total=max(1, total_docs))}
      </div>
      <div>
        <h2>Chunk 风险计数（best-effort）</h2>
        {_render_bar_table([("coverage_low", coverage_low), ("overlap_waste_high", overlap_high), ("token_stats_missing", tokens_missing)], total=max(1, total_docs))}
      </div>
    </div>

    <div class="section two">
      <div>
        <h2>Governance Metrics</h2>
        <table class="bars">
          <thead><tr><th>Metric</th><th>Value</th><th></th></tr></thead>
          <tbody>
            <tr><td class="k">docs_with_governance</td><td class="v">{_fmt_int(govd.get("docs_with_governance") or 0)}</td><td></td></tr>
            <tr><td class="k">rules_applied_total</td><td class="v">{_fmt_int(govd.get("rules_applied_total") or 0)}</td><td></td></tr>
            <tr><td class="k">dropped_documents_total</td><td class="v">{_fmt_int(govd.get("dropped_documents_total") or 0)}</td><td></td></tr>
          </tbody>
        </table>
      </div>
      <div>
        <h2>Drop Reasons（Top）</h2>
        {_render_bar_table(drop_reasons, total=max(1, sum(v for _, v in drop_reasons) if drop_reasons else 1))}
      </div>
    </div>

    <div class="section">
      <h2>Rule Packs（Docs）</h2>
      {_render_bar_table(rule_packs, total=max(1, total_docs))}
    </div>

    {governance_audit_section}

    <div class="section two">
      <div>
        <h2>Knowledge Graph（KG）</h2>
        <table class="bars">
          <thead><tr><th>Metric</th><th>Value</th><th></th></tr></thead>
          <tbody>
            <tr><td class="k">events</td><td class="v">{_fmt_int(kg_events)}</td><td></td></tr>
            <tr><td class="k">entities</td><td class="v">{_fmt_int(kg_entities)}</td><td></td></tr>
            <tr><td class="k">links</td><td class="v">{_fmt_int(kg_links)}</td><td></td></tr>
            <tr><td class="k">events_with_chunk_id</td><td class="v">{_fmt_int(kg_events_with_chunk)}</td><td></td></tr>
            <tr><td class="k">events_with_page_ref</td><td class="v">{_fmt_int(kg_events_with_page)}</td><td></td></tr>
            <tr><td class="k">links_with_provenance</td><td class="v">{_fmt_int(kg_links_with_prov)}</td><td></td></tr>
            <tr><td class="k">links_with_page_ref</td><td class="v">{_fmt_int(kg_links_with_page)}</td><td></td></tr>
            <tr><td class="k">documents_with_kg_extracted_at</td><td class="v">{_fmt_int(kg_docs_extracted)}</td><td></td></tr>
            <tr><td class="k">documents_with_kg_events</td><td class="v">{_fmt_int(kg_docs_with_events)}</td><td></td></tr>
            <tr><td class="k">event_count_from_documents</td><td class="v">{_fmt_int(kg_event_count_from_docs)}</td><td></td></tr>
            <tr><td class="k">skipped_chunks_total</td><td class="v">{_fmt_int(kg_skipped_chunks)}</td><td></td></tr>
            <tr><td class="k">skipped_short_chunks_total</td><td class="v">{_fmt_int(kg_skipped_short)}</td><td></td></tr>
            <tr><td class="k">failed_chunks_total</td><td class="v">{_fmt_int(kg_failed_chunks)}</td><td></td></tr>
            <tr><td class="k">retry_chunks_total</td><td class="v">{_fmt_int(kg_retry_chunks)}</td><td></td></tr>
            <tr><td class="k">updated_at</td><td class="v">{escape(kg_updated_at)}</td><td></td></tr>
          </tbody>
        </table>
      </div>
      <div>
        <h2>实体类型（Top）</h2>
        {_render_bar_table(kg_types, total=max(1, sum(v for _, v in kg_types) if kg_types else 1))}
      </div>
    </div>

    <div class="section">
      <h2>KG Drilldown（Top Documents）</h2>
      {kg_top_docs_table}
    </div>

    <div class="section two">
      <div>
        <h2>评估（Latest Regression Run）</h2>
        <table class="bars">
          <thead><tr><th>Field</th><th>Value</th><th></th></tr></thead>
          <tbody>
            <tr><td class="k">status</td><td class="v">{escape(rr_status)}</td><td></td></tr>
            <tr><td class="k">created_at</td><td class="v">{escape(rr_created_at)}</td><td></td></tr>
            <tr><td class="k">finished_at</td><td class="v">{escape(rr_finished_at)}</td><td></td></tr>
          </tbody>
        </table>
      </div>
      <div>
        <h2>评估 Summary</h2>
        {rr_summary_table}
      </div>
    </div>

    {retrieval_audit_section}

    {rr_slices_section}

    <div class="section">
      <h2>Raw JSON（用于审计/分享）</h2>
      <pre>{escape(raw_json)}</pre>
    </div>

    <div class="footer">
      <div>说明：本报告聚合 profile/governance/chunk/KG/eval 的客观指标，用于审计与回归对比。</div>
    </div>
  </div>
</body>
</html>
"""
    return html


def render_precheck_html(
    *,
    title: str,
    dataset_name: str | None,
    dataset_id: str | None,
    root_path: str | None,
    generated_at: datetime | str | None,
    summary: dict,
    samples: dict | None = None,
    redact: bool = False,
) -> str:
    name = _display_identity(redact=redact, value=dataset_name)
    dsid = _display_identity(redact=redact, value=dataset_id)
    rp = _display_identity(redact=redact, value=root_path)
    ts = _format_generated_at(generated_at)

    total_files = _int_from(summary, "total_files")
    total_bytes = _int_from(summary, "total_size_bytes")
    p50 = _percentile_int(summary, "length_percentiles", "p50")
    p90 = _percentile_int(summary, "length_percentiles", "p90")
    tok_p50 = _percentile_int(summary, "token_percentiles", "p50")
    tok_p90 = _percentile_int(summary, "token_percentiles", "p90")

    pdf = _as_dict(summary.get("pdf_scan"))
    pdf_scanned = _int_from(pdf, "scanned")
    pdf_text = _int_from(pdf, "not_scanned")
    pdf_unknown = _int_from(pdf, "unknown")

    by_type = _as_items(summary.get("by_file_type"), top=12)
    lang = _as_items(summary.get("language_mix"), top=4)
    pii = _as_items(summary.get("pii_hits_total"), top=12)
    secrets = _as_items(summary.get("secrets_hits_total"), top=12)
    primary_tags = _as_items(summary.get("primary_tag_counts"), top=12)
    processing_paths = _as_items(summary.get("processing_path_counts"), top=12)
    tips_html = _render_precheck_tips_html(
        summary=summary,
        pdf_scanned=pdf_scanned,
        p90=p90,
        tok_p90=tok_p90,
        pii=pii,
        secrets=secrets,
    )
    finding_rows = _collect_labeled_counts(summary.get("findings"))
    pdf_det = _as_dict(summary.get("pdf_detection"))
    samples_section = _render_precheck_samples_section(samples)

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #0b1020;
      --card: rgba(255,255,255,.06);
      --muted: rgba(255,255,255,.65);
      --text: rgba(255,255,255,.92);
      --border: rgba(255,255,255,.10);
      --accent: #38bdf8;
      --accent2: #22c55e;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      --sans: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji", "Segoe UI Emoji";
    }}
    body {{ margin: 0; background: radial-gradient(1200px 800px at 10% 10%, rgba(34,197,94,.12), transparent), var(--bg); color: var(--text); font-family: var(--sans); }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 28px 18px 40px; }}
    .title {{ font-size: 22px; font-weight: 800; letter-spacing: .2px; }}
    .sub {{ margin-top: 6px; color: var(--muted); font-size: 13px; }}
    .grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-top: 16px; }}
    .card {{ border: 1px solid var(--border); border-radius: 14px; background: var(--card); padding: 12px 12px; }}
    .kpi-label {{ color: var(--muted); font-size: 12px; }}
    .kpi-value {{ font-family: var(--mono); font-weight: 800; font-size: 18px; margin-top: 6px; }}
    .section {{ margin-top: 16px; border: 1px solid var(--border); border-radius: 14px; background: rgba(0,0,0,.12); padding: 14px 14px; }}
    .section h2 {{ margin: 0 0 10px; font-size: 14px; letter-spacing: .2px; }}
    .two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .empty {{ color: var(--muted); font-size: 13px; padding: 18px 0; text-align: center; }}
    table.bars {{ width: 100%; border-collapse: collapse; }}
    table.bars th {{ text-align: left; font-size: 12px; color: var(--muted); font-family: var(--mono); padding: 8px 6px; border-bottom: 1px solid var(--border); }}
    table.bars td {{ padding: 7px 6px; border-bottom: 1px solid rgba(255,255,255,.06); vertical-align: middle; }}
    table.bars td.k {{ font-family: var(--mono); font-size: 12px; color: var(--text); max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    table.bars td.v {{ font-family: var(--mono); font-size: 12px; color: var(--muted); width: 90px; }}
    .bar-bg {{ height: 10px; border-radius: 99px; background: rgba(255,255,255,.08); overflow: hidden; }}
    .bar-fill {{ height: 10px; border-radius: 99px; background: linear-gradient(90deg, var(--accent), rgba(34,197,94,.9)); }}
    .notes {{ color: var(--muted); font-size: 13px; line-height: 1.6; }}
    .notes ul {{ margin: 0; padding-left: 18px; }}
    .notes li {{ margin: 6px 0; }}
    .footer {{ margin-top: 18px; color: var(--muted); font-size: 12px; }}
    @media (max-width: 980px) {{ .grid {{ grid-template-columns: repeat(2, 1fr); }} .two {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="title">{escape(title)}</div>
    <div class="sub">dataset: <span style="font-family:var(--mono)">{escape(name)}</span> · id: <span style="font-family:var(--mono)">{escape(dsid)}</span> · root: <span style="font-family:var(--mono)">{escape(rp)}</span> · generated_at: <span style="font-family:var(--mono)">{escape(ts)}</span></div>

    <div class="grid">
      <div class="card"><div class="kpi-label">文件总数</div><div class="kpi-value">{_fmt_int(total_files)}</div></div>
      <div class="card"><div class="kpi-label">总大小</div><div class="kpi-value">{escape(_fmt_bytes(total_bytes))}</div></div>
      <div class="card"><div class="kpi-label">P50 文本长度（chars）</div><div class="kpi-value">{_fmt_int(p50)}</div></div>
      <div class="card"><div class="kpi-label">P90 文本长度（chars）</div><div class="kpi-value">{_fmt_int(p90)}</div></div>
      <div class="card"><div class="kpi-label">PDF 扫描/文本/未知</div><div class="kpi-value">{_fmt_int(pdf_scanned)}/{_fmt_int(pdf_text)}/{_fmt_int(pdf_unknown)}</div></div>
      <div class="card"><div class="kpi-label">P50 文本长度（tokens）</div><div class="kpi-value">{_fmt_int(tok_p50)}</div></div>
      <div class="card"><div class="kpi-label">P90 文本长度（tokens）</div><div class="kpi-value">{_fmt_int(tok_p90)}</div></div>
    </div>

    <div class="section">
      <h2>格式分布（Top）</h2>
      {_render_bar_table(by_type, total=total_files)}
    </div>

    <div class="section two">
      <div>
        <h2>长度分布（chars）</h2>
        {_render_histogram(summary.get("length_histogram"))}
      </div>
      <div>
        <h2>长度分布（tokens）</h2>
        {_render_histogram(summary.get("token_histogram"))}
      </div>
    </div>

    <div class="section">
      <h2>语言分布（抽样）</h2>
      {_render_bar_table(lang, total=max(1, total_files))}
    </div>

    <div class="section">
      <h2>文件大小分布</h2>
      {_render_histogram(summary.get("file_size_histogram"))}
    </div>

    <div class="section">
      <h2>目录结构（Top 风险聚集区）</h2>
      {_render_precheck_dir_table(summary.get("directory_stats"), redact=redact, max_rows=20)}
    </div>

    <div class="section two">
      <div>
        <h2>主标签分布</h2>
        {_render_bar_table(primary_tags, total=max(1, total_files))}
      </div>
      <div>
        <h2>处理路径建议</h2>
        {_render_bar_table(processing_paths, total=max(1, total_files))}
      </div>
    </div>

    <div class="section two">
      <div>
        <h2>PII 命中（次数）</h2>
        {_render_bar_table(pii, total=max(1, sum(v for _, v in pii) if pii else 1))}
      </div>
      <div>
        <h2>Secrets/Token 命中（次数）</h2>
        {_render_bar_table(secrets, total=max(1, sum(v for _, v in secrets) if secrets else 1))}
      </div>
    </div>

    <div class="section">
      <h2>问题清单（可操作）</h2>
      {_render_bar_table(finding_rows, total=max(1, total_files))}
    </div>

    <div class="section">
      <h2>入库建议（best-effort）</h2>
      {tips_html}
    </div>

    <div class="section">
      <h2>PDF 判定参数（透明阈值）</h2>
      <table class="bars">
        <thead><tr><th>Key</th><th>Value</th><th></th></tr></thead>
        <tbody>
          <tr><td class="k">sample_pages</td><td class="v">{escape(str(pdf_det.get("sample_pages") or ""))}</td><td></td></tr>
          <tr><td class="k">scan_max_chars_per_page</td><td class="v">{escape(str(pdf_det.get("scan_max_chars_per_page") or ""))}</td><td></td></tr>
          <tr><td class="k">text_min_chars_per_page</td><td class="v">{escape(str(pdf_det.get("text_min_chars_per_page") or ""))}</td><td></td></tr>
          <tr><td class="k">scan_ratio_threshold</td><td class="v">{escape(str(pdf_det.get("scan_ratio_threshold") or ""))}</td><td></td></tr>
        </tbody>
      </table>
    </div>

    {samples_section}

    <div class="footer">
      <div>说明：预检扫描以“入库前摸底”为目标，输出客观统计与待复核清单；不做主观评分。</div>
    </div>
  </div>
</body>
</html>
"""
    return html
