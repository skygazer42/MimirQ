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

EMPTY_DATA_DIV = "<div class=\"empty\">暂无数据</div>"
TABLE_TBODY_CLOSE = '</tbody></table>'
REDACTED_TEXT = '[REDACTED]'
BARS_METRIC_TABLE_HEADER = "<table class=\"bars\"><thead><tr><th>Metric</th><th>Value</th><th></th></tr></thead><tbody>"
EMPTY_BRIEF_DIV = "<div class=\"empty\">暂无</div>"
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
            f"<td class=\"k\">{escape(str(k))}</td>"
            f"<td class=\"v\">{_fmt_int(v)}</td>"
            f"<td class=\"bar\"><div class=\"bar-bg\"><div class=\"bar-fill\" style=\"width:{pct:.2f}%\"></div></div></td>"
            "</tr>"
        )
    return (
        "<table class=\"bars\">"
        "<thead><tr><th>Key</th><th>Count</th><th style=\"width:55%\">Ratio</th></tr></thead>"
        "<tbody>"
        + "".join(rows)
        + TABLE_TBODY_CLOSE
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
            if isinstance(metrics.get(key), bool) or (isinstance(metrics.get(key), (int, float)) and not isinstance(metrics.get(key), bool))
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
        "failure_categories": {str(key): int(value or 0) for key, value in failure_categories.items() if str(key or "").strip()},
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
            f"<tr><td class=\"k\">{escape(key)}</td><td class=\"v\">{escape(value)}</td><td></td></tr>"
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
                f"<td class=\"k\">{escape(f'{gate_name}.{key}')}</td>"
                f"<td class=\"v\">{escape(_fmt_scalar(metrics.get(key)))}</td>"
                "<td></td>"
                "</tr>"
            )
    metric_table = (
        BARS_METRIC_TABLE_HEADER
        + "".join(metric_rows[:40])
        + TABLE_TBODY_CLOSE
        if metric_rows
        else EMPTY_DATA_DIV
    )

    return (
        "<div class=\"section two\">"
        "<div><h2>Retrieval Audit</h2>"
        f"{meta_table}"
        "</div>"
        "<div><h2>Retrieval Audit Metrics</h2>"
        f"{metric_table}"
        "</div>"
        "</div>"
    )


def _scrub_report_for_redaction(report: Any) -> dict:
    """
    Best-effort scrubber for `redact=True` HTML exports.

    Goal: prevent leaking dataset identity / paths / internal IDs via the embedded Raw JSON block.
    We keep objective, aggregate metrics that are already rendered elsewhere in the HTML.
    """

    if not isinstance(report, dict):
        return {"redacted": True}

    def _select(source: Any, keys: set[str]) -> dict[str, Any]:
        if not isinstance(source, dict):
            return {}
        return {key: source[key] for key in keys if key in source}

    def _objective_metrics(value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, dict):
            return {
                str(key): scrubbed
                for key, item in value.items()
                if (scrubbed := _objective_metrics(item)) is not None
            }
        if isinstance(value, list):
            return [scrubbed for item in value if (scrubbed := _objective_metrics(item)) is not None]
        return None

    safe: dict[str, Any] = {"redacted": True}
    if "dataset_name" in report:
        safe["dataset_name"] = REDACTED_TEXT
    if "dataset_id" in report:
        safe["dataset_id"] = REDACTED_TEXT

    profile = _select(
        report.get("profile"),
        {
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
        },
    )
    if profile:
        safe["profile"] = profile

    compliance = _select(
        report.get("compliance"),
        {"pii_hits_total", "secrets_hits_total", "quarantined_documents", "failed_documents"},
    )
    if compliance:
        safe["compliance"] = compliance

    for section in ("governance_metrics", "governance_audit", "chunk_quality_metrics"):
        objective = _objective_metrics(report.get(section))
        if isinstance(objective, dict) and objective:
            safe[section] = objective

    kg = _select(
        report.get("kg_stats"),
        {
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
        },
    )
    if kg:
        safe["kg_stats"] = kg

    regression = report.get("latest_regression_run")
    if isinstance(regression, dict):
        regression_safe = _select(regression, {"status", "metrics"})
        summary = _objective_metrics(regression.get("summary"))
        if isinstance(summary, dict) and summary:
            regression_safe["summary"] = summary
        if regression_safe:
            safe["latest_regression_run"] = regression_safe

    retrieval_audit = report.get("retrieval_audit")
    if isinstance(retrieval_audit, dict):
        audit_safe = _select(retrieval_audit, {"status", "failure_categories"})
        if audit_safe:
            safe["retrieval_audit"] = audit_safe

    precheck = _select(
        report.get("precheck_summary"),
        {
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
        },
    )
    if precheck:
        safe["precheck_summary"] = precheck

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
    p50 = int(((summary.get("length_percentiles") or {}) if isinstance(summary.get("length_percentiles"), dict) else {}).get("p50") or 0)
    p90 = int(((summary.get("length_percentiles") or {}) if isinstance(summary.get("length_percentiles"), dict) else {}).get("p90") or 0)
    chunk_p50 = int(((summary.get("chunk_count_percentiles") or {}) if isinstance(summary.get("chunk_count_percentiles"), dict) else {}).get("p50") or 0)
    avg_chunk_p50 = int(((summary.get("avg_chunk_chars_percentiles") or {}) if isinstance(summary.get("avg_chunk_chars_percentiles"), dict) else {}).get("p50") or 0)
    chunk_len_p50 = int(((summary.get("chunk_length_percentiles") or {}) if isinstance(summary.get("chunk_length_percentiles"), dict) else {}).get("p50") or 0)
    chunk_tok_p50 = int(((summary.get("chunk_token_percentiles") or {}) if isinstance(summary.get("chunk_token_percentiles"), dict) else {}).get("p50") or 0)
    avg_chunk_tok_p50 = int(((summary.get("avg_chunk_tokens_percentiles") or {}) if isinstance(summary.get("avg_chunk_tokens_percentiles"), dict) else {}).get("p50") or 0)
    cov_p50 = int(((summary.get("chunk_coverage_percentiles") or {}) if isinstance(summary.get("chunk_coverage_percentiles"), dict) else {}).get("p50") or 0)
    waste_p50 = int(((summary.get("chunk_overlap_waste_percentiles") or {}) if isinstance(summary.get("chunk_overlap_waste_percentiles"), dict) else {}).get("p50") or 0)

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
    name = REDACTED_TEXT if redact else (dataset_name or "")
    dsid = REDACTED_TEXT if redact else (dataset_id or "")
    ts = generated_at.isoformat() if isinstance(generated_at, datetime) else (str(generated_at or "") or "")

    profile = report.get("profile") if isinstance(report, dict) else None
    prof = profile if isinstance(profile, dict) else {}

    total_docs = int(prof.get("total_documents") or 0)
    total_bytes = int(prof.get("total_size_bytes") or 0)

    by_status = _as_items(prof.get("by_status"), top=12)
    by_type = _as_items(prof.get("by_file_type"), top=12)

    # Actionable findings (best-effort; derived from profile.findings).
    findings = prof.get("findings") if isinstance(prof.get("findings"), list) else []
    finding_rows: list[tuple[str, int]] = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        key = str(f.get("label") or f.get("key") or "").strip() or "unknown"
        try:
            cnt = int(f.get("count") or 0)
        except Exception:
            cnt = 0
        if cnt <= 0:
            continue
        finding_rows.append((key, cnt))
    finding_rows.sort(key=lambda kv: (-kv[1], kv[0]))

    # Parsing provenance/routing (best-effort; derived from profile.parsing_provenance).
    prov = prof.get("parsing_provenance") if isinstance(prof.get("parsing_provenance"), dict) else {}
    prov_docs = int(prov.get("docs_with_provenance") or 0)
    prov_fallback_docs = int(prov.get("fallback_docs") or 0)
    prov_by_backend = _as_items(prov.get("by_resolved_backend"), top=12)
    prov_elapsed = prov.get("elapsed_ms_percentiles") if isinstance(prov.get("elapsed_ms_percentiles"), dict) else {}
    prov_elapsed_p50 = int(prov_elapsed.get("p50") or 0)
    prov_elapsed_p90 = int(prov_elapsed.get("p90") or 0)
    prov_meta_rows = [
        ("docs_with_provenance", prov_docs),
        ("fallback_docs", prov_fallback_docs),
        ("p50_elapsed_ms", prov_elapsed_p50),
        ("p90_elapsed_ms", prov_elapsed_p90),
    ]
    prov_meta_table = (
        BARS_METRIC_TABLE_HEADER
        + "".join(f'<tr><td class="k">{escape(str(k))}</td><td class="v">{_fmt_int(v)}</td><td></td></tr>' for k, v in prov_meta_rows)
        + TABLE_TBODY_CLOSE
        if prov_meta_rows
        else EMPTY_DATA_DIV
    )

    # Chunk target checks (best-effort; derived from profile.chunk_targets).
    chunk_targets = prof.get("chunk_targets") if isinstance(prof.get("chunk_targets"), list) else []
    ct_rows: list[str] = []
    for t in chunk_targets:
        if not isinstance(t, dict):
            continue
        label = str(t.get("label") or t.get("key") or "").strip() or "unknown"
        status = str(t.get("status") or "").strip() or "unknown"
        msg = str(t.get("message") or "").strip()
        sugg_raw = t.get("suggestions")
        sugg_list = sugg_raw if isinstance(sugg_raw, list) else []
        suggestions = "; ".join([str(s).strip() for s in sugg_list if str(s).strip()])[:500]
        ct_rows.append(
            "<tr>"
            f"<td class=\"k\">{escape(label)}</td>"
            f"<td class=\"v\">{escape(status)}</td>"
            f"<td class=\"v\">{escape(msg)}</td>"
            f"<td class=\"v\">{escape(suggestions)}</td>"
            "</tr>"
        )
    chunk_targets_table = (
        "<table class=\"bars\"><thead><tr><th>Check</th><th>Status</th><th>Message</th><th>Suggestions</th></tr></thead><tbody>"
        + "".join(ct_rows)
        + TABLE_TBODY_CLOSE
        if ct_rows
        else EMPTY_DATA_DIV
    )

    # Retrieval recall-risk hints (best-effort; from profile.recall_risk_hints).
    recall_risk_hints = prof.get("recall_risk_hints") if isinstance(prof.get("recall_risk_hints"), list) else []
    rrh_rows: list[str] = []
    for h in recall_risk_hints:
        if not isinstance(h, dict):
            continue
        label = str(h.get("label") or h.get("key") or "").strip() or "unknown"
        severity = str(h.get("severity") or "").strip() or "warning"
        msg = str(h.get("message") or "").strip()
        observed = h.get("observed") if isinstance(h.get("observed"), dict) else {}
        observed_str = ", ".join(
            [f"{str(k)}={str(v)}" for k, v in sorted(observed.items(), key=lambda kv: str(kv[0] or ""))[:6]]
        )[:220]
        rrh_rows.append(
            "<tr>"
            f"<td class=\"k\">{escape(label)}</td>"
            f"<td class=\"v\">{escape(severity)}</td>"
            f"<td class=\"v\">{escape(observed_str)}</td>"
            f"<td class=\"v\">{escape(msg)}</td>"
            "</tr>"
        )
    recall_risk_table = (
        "<table class=\"bars\"><thead><tr><th>Hint</th><th>Severity</th><th>Observed</th><th>Message</th></tr></thead><tbody>"
        + "".join(rrh_rows)
        + TABLE_TBODY_CLOSE
        if rrh_rows
        else EMPTY_DATA_DIV
    )

    comp = report.get("compliance") if isinstance(report, dict) else None
    compd = comp if isinstance(comp, dict) else {}
    quarantined = int(compd.get("quarantined_documents") or 0)
    failed = int(compd.get("failed_documents") or 0)

    versions = report.get("pipeline_versions") if isinstance(report, dict) else None
    version_items: list[tuple[str, int]] = []
    if isinstance(versions, list):
        for v in versions:
            if not isinstance(v, dict):
                continue
            ph = str(v.get("pipeline_hash") or "").strip() or "unknown"
            try:
                cnt = int(v.get("documents") or 0)
            except Exception:
                cnt = 0
            if cnt <= 0:
                continue
            version_items.append((ph, cnt))

    connectors = report.get("connectors") if isinstance(report, dict) else None
    conn_rows: list[str] = []
    if isinstance(connectors, list):
        for r in connectors[:30]:
            if not isinstance(r, dict):
                continue
            conn_rows.append(
                "<tr>"
                f"<td class=\"k\">{escape(str(r.get('connector_id') or ''))}</td>"
                f"<td class=\"v\">{escape(str(r.get('status') or ''))}</td>"
                f"<td class=\"v\">{escape(str(r.get('created_at') or ''))}</td>"
                "</tr>"
            )

    cqm = report.get("chunk_quality_metrics") if isinstance(report, dict) else None
    cqmd = cqm if isinstance(cqm, dict) else {}
    gate_grades = _as_items(cqmd.get("gate_grade_docs"), top=12)
    coverage_low = int(cqmd.get("coverage_low_documents") or 0)
    overlap_high = int(cqmd.get("overlap_waste_high_documents") or 0)
    tokens_missing = int(cqmd.get("token_stats_missing_documents") or 0)

    # Optional: KG stats (best-effort; may be null when disabled or empty).
    kg = report.get("kg_stats") if isinstance(report, dict) else None
    kgd = kg if isinstance(kg, dict) else {}
    kg_events = int(kgd.get("events") or 0)
    kg_entities = int(kgd.get("entities") or 0)
    kg_links = int(kgd.get("links") or 0)
    kg_events_with_chunk = int(kgd.get("events_with_chunk_id") or 0)
    kg_events_with_page = int(kgd.get("events_with_page_ref") or 0)
    kg_links_with_prov = int(kgd.get("links_with_provenance") or 0)
    kg_links_with_page = int(kgd.get("links_with_page_ref") or 0)
    kg_docs_extracted = int(kgd.get("documents_with_kg_extracted_at") or 0)
    kg_docs_with_events = int(kgd.get("documents_with_kg_events") or 0)
    kg_event_count_from_docs = int(kgd.get("event_count_from_documents") or 0)
    kg_skipped_chunks = int(kgd.get("skipped_chunks_total") or 0)
    kg_skipped_short = int(kgd.get("skipped_short_chunks_total") or 0)
    kg_failed_chunks = int(kgd.get("failed_chunks_total") or 0)
    kg_retry_chunks = int(kgd.get("retry_chunks_total") or 0)
    kg_updated_at = str(kgd.get("updated_at") or "").strip()
    kg_type_items: list[tuple[str, int]] = []
    raw_types = kgd.get("entity_types")
    if isinstance(raw_types, list):
        for t in raw_types[:50]:
            if not isinstance(t, dict):
                continue
            tp = str(t.get("type") or "").strip() or "unknown"
            try:
                cnt = int(t.get("count") or 0)
            except Exception:
                cnt = 0
            if cnt <= 0:
                continue
            kg_type_items.append((tp, cnt))

    # Optional: KG drilldown (top docs by event_count). Render only when not redacting.
    kg_top_docs = kgd.get("top_documents") if isinstance(kgd.get("top_documents"), list) else []
    kg_doc_rows: list[str] = []
    if not redact and isinstance(kg_top_docs, list):
        for r in kg_top_docs[:10]:
            if not isinstance(r, dict):
                continue
            did = str(r.get("document_id") or "").strip()
            if not did:
                continue
            src = str(r.get("source") or "").strip()
            try:
                evc = int(r.get("event_count") or 0)
            except Exception:
                evc = 0
            try:
                sk = int(r.get("skipped_chunks") or 0)
            except Exception:
                sk = 0
            try:
                fs = int(r.get("failed_chunks") or 0)
            except Exception:
                fs = 0
            kg_doc_rows.append(
                "<tr>"
                f"<td class=\"k\">{escape(src or did[:8])}</td>"
                f"<td class=\"v\">{_fmt_int(evc)}</td>"
                f"<td class=\"v\">{_fmt_int(sk)}</td>"
                f"<td class=\"v\">{_fmt_int(fs)}</td>"
                "</tr>"
            )
    kg_top_docs_table = (
        "<table class=\"bars\"><thead><tr><th>doc</th><th>events</th><th>skipped</th><th>failed</th></tr></thead><tbody>"
        + "".join(kg_doc_rows)
        + TABLE_TBODY_CLOSE
        if kg_doc_rows
        else EMPTY_DATA_DIV
    )

    # Optional: latest regression run summary (best-effort).
    rr = report.get("latest_regression_run") if isinstance(report, dict) else None
    rrd = rr if isinstance(rr, dict) else {}
    rr_id = str(rrd.get("run_id") or "").strip()
    rr_status = str(rrd.get("status") or "").strip()
    rr_created_at = str(rrd.get("created_at") or "").strip()
    rr_started_at = str(rrd.get("started_at") or "").strip()
    rr_finished_at = str(rrd.get("finished_at") or "").strip()
    rr_metrics = rrd.get("metrics") if isinstance(rrd.get("metrics"), list) else []
    rr_metrics_str = ", ".join(str(x) for x in rr_metrics if str(x or "").strip())[:200]
    rr_summary = rrd.get("summary") if isinstance(rrd.get("summary"), dict) else {}

    def _fmt_num(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, bool):
            return "1" if v else "0"
        if isinstance(v, int) and not isinstance(v, bool):
            return _fmt_int(v)
        if isinstance(v, float):
            return f"{v:.4f}"
        return str(v)

    rr_meta_rows: list[str] = []
    if rr_id or rr_status or rr_metrics_str or rr_created_at or rr_finished_at:
        rr_meta_rows = [
            f"<tr><td class=\"k\">status</td><td class=\"v\">{escape(rr_status or '')}</td><td></td></tr>",
            f"<tr><td class=\"k\">run_id</td><td class=\"v\">{escape(rr_id or '')}</td><td></td></tr>",
            f"<tr><td class=\"k\">metrics</td><td class=\"v\">{escape(rr_metrics_str or '')}</td><td></td></tr>",
            f"<tr><td class=\"k\">created_at</td><td class=\"v\">{escape(rr_created_at or '')}</td><td></td></tr>",
            f"<tr><td class=\"k\">started_at</td><td class=\"v\">{escape(rr_started_at or '')}</td><td></td></tr>",
            f"<tr><td class=\"k\">finished_at</td><td class=\"v\">{escape(rr_finished_at or '')}</td><td></td></tr>",
        ]
    rr_meta_table = (
        "<table class=\"bars\"><thead><tr><th>Field</th><th>Value</th><th></th></tr></thead><tbody>"
        + "".join(rr_meta_rows)
        + TABLE_TBODY_CLOSE
        if rr_meta_rows
        else EMPTY_DATA_DIV
    )

    rr_summary_rows: list[str] = []
    for k, v in sorted((rr_summary or {}).items(), key=lambda kv: str(kv[0] or "")):
        key = str(k or "").strip()
        if not key:
            continue
        # Objective numbers only: keep numeric/bool values; skip nested dict/list blobs.
        if isinstance(v, bool) or (isinstance(v, (int, float)) and not isinstance(v, bool)):
            rr_summary_rows.append(f"<tr><td class=\"k\">{escape(key)}</td><td class=\"v\">{escape(_fmt_num(v))}</td><td></td></tr>")

    rr_summary_table = (
        BARS_METRIC_TABLE_HEADER
        + "".join(rr_summary_rows)
        + TABLE_TBODY_CLOSE
        if rr_summary_rows
        else EMPTY_DATA_DIV
    )

    # Optional: retrieval-only slicing summary (nested dict) for deeper diagnostics.
    rr_slices = rr_summary.get("retrieval_slices") if isinstance(rr_summary.get("retrieval_slices"), dict) else {}

    def _render_rr_slice_table(dim: str) -> str:
        if redact and dim == "directory":
            return '<div class="empty">已脱敏：directory 不展示</div>'
        obj = rr_slices.get(dim) if isinstance(rr_slices.get(dim), dict) else {}
        buckets = obj.get("buckets") if isinstance(obj.get("buckets"), list) else []
        rows: list[str] = []
        for b in buckets[:10]:
            if not isinstance(b, dict):
                continue
            key = str(b.get("key") or "").strip()
            if not key:
                continue
            try:
                items = int(b.get("items") or 0)
            except Exception:
                items = 0
            rows.append(
                "<tr>"
                f"<td class=\\\"k\\\">{escape(key)}</td>"
                f"<td class=\\\"v\\\">{_fmt_int(items)}</td>"
                f"<td class=\\\"v\\\">{escape(_fmt_num(b.get('retrieval_recall')))}</td>"
                f"<td class=\\\"v\\\">{escape(_fmt_num(b.get('retrieval_hit_at_20')))}</td>"
                f"<td class=\\\"v\\\">{escape(_fmt_num(b.get('retrieval_mrr')))}</td>"
                f"<td class=\\\"v\\\">{escape(_fmt_num(b.get('abstain_rate')))}</td>"
                "</tr>"
            )
        return (
            "<table class=\\\"bars\\\"><thead><tr><th>bucket</th><th>items</th><th>recall</th><th>hit@20</th><th>mrr</th><th>abstain</th></tr></thead><tbody>"
            + "".join(rows)
            + TABLE_TBODY_CLOSE
            if rows
            else '<div class=\"empty\">暂无数据</div>'
        )

    rr_slices_section = ""
    if rr_slices:
        rr_slices_section = (
            "<div class=\\\"section\\\">"
            "<h2>Retrieval Slices</h2>"
            "<div class=\\\"two\\\">"
            f"<div><h2>file_type</h2>{_render_rr_slice_table('file_type')}</div>"
            f"<div><h2>language</h2>{_render_rr_slice_table('language')}</div>"
            "</div>"
            "<div class=\\\"two\\\" style=\\\"margin-top:12px\\\">"
            f"<div><h2>hit_type</h2>{_render_rr_slice_table('hit_type')}</div>"
            f"<div><h2>quality</h2>{_render_rr_slice_table('quality')}</div>"
            "</div>"
            "<div class=\\\"two\\\" style=\\\"margin-top:12px\\\">"
            f"<div><h2>pipeline_hash</h2>{_render_rr_slice_table('pipeline_hash')}</div>"
            f"<div><h2>directory</h2>{_render_rr_slice_table('directory')}</div>"
            "</div>"
            "</div>"
        )

    retrieval_audit_section = _render_retrieval_audit_section(report)
    raw_report = _report_with_safe_retrieval_audit(report)
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

	    <div class="section two">
	      <div>
	        <h2>状态分布</h2>
	        {_render_bar_table(by_status, total=max(1, total_docs))}
	      </div>
	      <div>
	        <h2>格式分布（Top）</h2>
	        {_render_bar_table(by_type, total=max(1, total_docs))}
	      </div>
	    </div>

	    <div class="section two">
	      <div>
	        <h2>问题清单（可操作）</h2>
	        {_render_bar_table(finding_rows, total=max(1, total_docs))}
	      </div>
	      <div>
	        <h2>Parsing / Routing（Docs）</h2>
	        {_render_bar_table(prov_by_backend, total=max(1, prov_docs))}
	        <div style="margin-top:10px">{prov_meta_table}</div>
	      </div>
	    </div>

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

	    <div class="section">
	      <h2>Chunk Targets（分布目标检查）</h2>
	      {chunk_targets_table}
	    </div>

	    <div class="section">
	      <h2>召回风险摘要（Recall Risk Hints）</h2>
	      {recall_risk_table}
	    </div>

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
      {('<table class="bars"><thead><tr><th>connector_id</th><th>status</th><th>created_at</th></tr></thead><tbody>' + ''.join(conn_rows) + '</tbody></table>') if conn_rows else EMPTY_DATA_DIV}
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
    name = REDACTED_TEXT if redact else (dataset_name or "")
    dsid = REDACTED_TEXT if redact else (dataset_id or "")
    ts = generated_at.isoformat() if isinstance(generated_at, datetime) else (str(generated_at or "") or "")

    profile = report.get("profile") if isinstance(report, dict) else None
    prof = profile if isinstance(profile, dict) else {}

    total_docs = int(prof.get("total_documents") or 0)
    total_bytes = int(prof.get("total_size_bytes") or 0)

    by_status = _as_items(prof.get("by_status"), top=12)
    by_type = _as_items(prof.get("by_file_type"), top=12)

    p50 = int(((prof.get("length_percentiles") or {}) if isinstance(prof.get("length_percentiles"), dict) else {}).get("p50") or 0)
    p90 = int(((prof.get("length_percentiles") or {}) if isinstance(prof.get("length_percentiles"), dict) else {}).get("p90") or 0)
    chunk_tok_p50 = int(((prof.get("chunk_token_percentiles") or {}) if isinstance(prof.get("chunk_token_percentiles"), dict) else {}).get("p50") or 0)
    cov_p50 = int(((prof.get("chunk_coverage_percentiles") or {}) if isinstance(prof.get("chunk_coverage_percentiles"), dict) else {}).get("p50") or 0)

    comp = report.get("compliance") if isinstance(report, dict) else None
    compd = comp if isinstance(comp, dict) else {}
    quarantined = int(compd.get("quarantined_documents") or 0)
    failed = int(compd.get("failed_documents") or 0)

    gov = report.get("governance_metrics") if isinstance(report, dict) else None
    govd = gov if isinstance(gov, dict) else {}
    drop_reasons = _as_items(govd.get("drop_reasons_total"), top=12)
    rule_packs = _as_items(govd.get("rule_packs_docs"), top=12)

    # Optional: governance audit snapshot (effects/impact metrics).
    ga0 = report.get("governance_audit") if isinstance(report, dict) else None
    ga = ga0 if isinstance(ga0, dict) else {}
    ga_used_docs = int(ga.get("used_documents") or 0)
    ga_truncated = bool(ga.get("truncated") or False)
    ga_persisted_docs = int(ga.get("docs_with_parsed_content_persisted") or 0)
    ga_persisted_trunc_docs = int(ga.get("parsed_content_truncated_docs") or 0)
    ga_char_stats_docs = int(ga.get("docs_with_char_stats") or ga_persisted_docs or 0)
    ga_quality_docs = int(ga.get("docs_with_governance_quality") or 0)
    ga_orig_chars = int(ga.get("original_chars_total") or 0)
    ga_clean_chars = int(ga.get("cleaned_chars_total") or 0)
    try:
        ga_char_reduction_ratio = float(ga.get("char_reduction_ratio") or 0.0)
    except Exception:
        ga_char_reduction_ratio = 0.0
    ga_char_reduction_ratio = max(0.0, min(1.0, ga_char_reduction_ratio))
    pct0 = ga.get("char_reduction_pct_percentiles") if isinstance(ga.get("char_reduction_pct_percentiles"), dict) else {}
    ga_char_reduction_p50 = int(pct0.get("p50") or 0)
    ga_char_reduction_p90 = int(pct0.get("p90") or 0)
    ga_char_reduction_p99 = int(pct0.get("p99") or 0)

    dens0 = ga.get("density_pct_percentiles") if isinstance(ga.get("density_pct_percentiles"), dict) else {}
    ga_density_p50 = int(dens0.get("p50") or 0)
    ga_density_p90 = int(dens0.get("p90") or 0)

    head0 = ga.get("heading_ratio_pct_percentiles") if isinstance(ga.get("heading_ratio_pct_percentiles"), dict) else {}
    ga_heading_p50 = int(head0.get("p50") or 0)
    ga_heading_p90 = int(head0.get("p90") or 0)
    ga_docs_changed = int(ga.get("docs_changed") or 0)
    ga_docs_dropped = int(ga.get("docs_dropped") or 0)

    ga_paras_dropped = int(ga.get("paragraphs_dropped_total") or 0)
    ga_refs_removed = int(ga.get("references_removed_lines_total") or 0)
    ga_urls_changed = int(ga.get("urls_changed_total") or 0)
    ga_boiler_sections = int(ga.get("boilerplate_removed_sections_total") or 0)
    ga_boiler_lines = int(ga.get("boilerplate_removed_lines_total") or 0)
    ga_images_removed = int(ga.get("images_removed_total") or 0)
    ga_tables_norm = int(ga.get("tables_normalized_total") or 0)
    ga_table_rows_changed = int(ga.get("table_rows_changed_total") or 0)
    ga_code_lines_stripped = int(ga.get("code_lines_stripped_total") or 0)

    governance_audit_section = ""
    if isinstance(ga0, dict) and ga0:
        ratio_str = f"{ga_char_reduction_ratio:.2f} ({ga_char_reduction_ratio * 100.0:.1f}%)"
        audit_note = ""
        if ga_used_docs > 0:
            audit_note = f"<div class=\\\"sub\\\" style=\\\"margin-top:6px\\\">sample: {escape(_fmt_int(ga_used_docs))}{' (truncated)' if ga_truncated else ''}</div>"

        governance_audit_section = (
            "<div class=\\\"section\\\">"
            "<h2>Governance Audit（治理效果）</h2>"
            f"{audit_note}"
            "<table class=\\\"bars\\\">"
            "<thead><tr><th>Metric</th><th>Value</th><th></th></tr></thead>"
            "<tbody>"
            f"<tr><td class=\\\"k\\\">docs_changed</td><td class=\\\"v\\\">{_fmt_int(ga_docs_changed)}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">docs_dropped</td><td class=\\\"v\\\">{_fmt_int(ga_docs_dropped)}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">docs_with_char_stats</td><td class=\\\"v\\\">{_fmt_int(ga_char_stats_docs)}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">docs_with_parsed_content_persisted</td><td class=\\\"v\\\">{_fmt_int(ga_persisted_docs)}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">parsed_content_truncated_docs</td><td class=\\\"v\\\">{_fmt_int(ga_persisted_trunc_docs)}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">original_chars_total</td><td class=\\\"v\\\">{_fmt_int(ga_orig_chars)}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">cleaned_chars_total</td><td class=\\\"v\\\">{_fmt_int(ga_clean_chars)}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">char_reduction_ratio</td><td class=\\\"v\\\">{escape(ratio_str)}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">char_reduction_pct_p50</td><td class=\\\"v\\\">{escape(f'{_fmt_int(ga_char_reduction_p50)}%')}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">char_reduction_pct_p90</td><td class=\\\"v\\\">{escape(f'{_fmt_int(ga_char_reduction_p90)}%')}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">char_reduction_pct_p99</td><td class=\\\"v\\\">{escape(f'{_fmt_int(ga_char_reduction_p99)}%')}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">docs_with_governance_quality</td><td class=\\\"v\\\">{_fmt_int(ga_quality_docs)}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">density_pct_p50</td><td class=\\\"v\\\">{escape(f'{_fmt_int(ga_density_p50)}%')}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">density_pct_p90</td><td class=\\\"v\\\">{escape(f'{_fmt_int(ga_density_p90)}%')}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">heading_ratio_pct_p50</td><td class=\\\"v\\\">{escape(f'{_fmt_int(ga_heading_p50)}%')}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">heading_ratio_pct_p90</td><td class=\\\"v\\\">{escape(f'{_fmt_int(ga_heading_p90)}%')}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">paragraphs_dropped_total</td><td class=\\\"v\\\">{_fmt_int(ga_paras_dropped)}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">references_removed_lines_total</td><td class=\\\"v\\\">{_fmt_int(ga_refs_removed)}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">urls_changed_total</td><td class=\\\"v\\\">{_fmt_int(ga_urls_changed)}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">boilerplate_removed_sections_total</td><td class=\\\"v\\\">{_fmt_int(ga_boiler_sections)}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">boilerplate_removed_lines_total</td><td class=\\\"v\\\">{_fmt_int(ga_boiler_lines)}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">images_removed_total</td><td class=\\\"v\\\">{_fmt_int(ga_images_removed)}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">tables_normalized_total</td><td class=\\\"v\\\">{_fmt_int(ga_tables_norm)}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">table_rows_changed_total</td><td class=\\\"v\\\">{_fmt_int(ga_table_rows_changed)}</td><td></td></tr>"
            f"<tr><td class=\\\"k\\\">code_lines_stripped_total</td><td class=\\\"v\\\">{_fmt_int(ga_code_lines_stripped)}</td><td></td></tr>"
            + TABLE_TBODY_CLOSE
            + "</div>"
        )

    cqm = report.get("chunk_quality_metrics") if isinstance(report, dict) else None
    cqmd = cqm if isinstance(cqm, dict) else {}
    gate_grades = _as_items(cqmd.get("gate_grade_docs"), top=12)
    coverage_low = int(cqmd.get("coverage_low_documents") or 0)
    overlap_high = int(cqmd.get("overlap_waste_high_documents") or 0)
    tokens_missing = int(cqmd.get("token_stats_missing_documents") or 0)

    # Optional: latest precheck summary snapshot (before ingestion).
    precheck_summary = report.get("precheck_summary") if isinstance(report, dict) else None
    pre = precheck_summary if isinstance(precheck_summary, dict) else {}
    pre_total_files = int(pre.get("total_files") or 0)
    pre_total_bytes = int(pre.get("total_size_bytes") or 0)
    pre_scan_run_id = REDACTED_TEXT if redact else str(pre.get("scan_run_id") or "").strip()
    pre_generated_at = str(pre.get("generated_at") or "").strip()
    pre_by_type = _as_items(pre.get("by_file_type"), top=12)
    pre_lang = _as_items(pre.get("language_mix"), top=4)
    pre_pii = _as_items(pre.get("pii_hits_total"), top=12)
    pre_secrets = _as_items(pre.get("secrets_hits_total"), top=12)

    pdf0 = pre.get("pdf_scan") if isinstance(pre.get("pdf_scan"), dict) else {}
    pre_pdf_scanned = int(pdf0.get("scanned") or 0)
    pre_pdf_text = int(pdf0.get("not_scanned") or 0)
    pre_pdf_unknown = int(pdf0.get("unknown") or 0)

    pre_findings = pre.get("findings") if isinstance(pre.get("findings"), list) else []
    pre_finding_rows: list[tuple[str, int]] = []
    for f in pre_findings:
        if not isinstance(f, dict):
            continue
        key = str(f.get("label") or f.get("key") or "").strip() or "unknown"
        try:
            cnt = int(f.get("count") or 0)
        except Exception:
            cnt = 0
        if cnt > 0:
            pre_finding_rows.append((key, cnt))
    pre_finding_rows.sort(key=lambda kv: (-kv[1], kv[0]))

    def _render_pre_dir_table(items: Any, *, max_rows: int = 20) -> str:
        if redact:
            return '<div class="empty">已脱敏：目录结构不展示</div>'
        if not isinstance(items, list) or not items:
            return EMPTY_DATA_DIV
        rows: list[str] = []
        for obj in items[: max(0, int(max_rows))]:
            if not isinstance(obj, dict):
                continue
            path = escape(str(obj.get("path") or "."))
            total_files = int(obj.get("total_files") or 0)
            risky_files = int(obj.get("risky_files") or 0)
            size_bytes = _fmt_bytes(obj.get("total_size_bytes") or 0)
            rows.append(
                "<tr>"
                f"<td class=\"k\">{path}</td>"
                f"<td class=\"v\">{_fmt_int(risky_files)}/{_fmt_int(total_files)}</td>"
                f"<td class=\"v\">{escape(size_bytes)}</td>"
                "</tr>"
            )
        if not rows:
            return EMPTY_DATA_DIV
        return (
            "<table class=\"bars\">"
            "<thead><tr><th>Directory</th><th>Risky/Total</th><th>Bytes</th></tr></thead>"
            "<tbody>"
            + "".join(rows)
            + TABLE_TBODY_CLOSE
        )

    precheck_section = ""
    if isinstance(precheck_summary, dict) and precheck_summary:
        pre_meta = (
            "<table class=\"bars\">"
            "<thead><tr><th>Field</th><th>Value</th><th></th></tr></thead>"
            "<tbody>"
            f"<tr><td class=\"k\">scan_run_id</td><td class=\"v\">{escape(pre_scan_run_id)}</td><td></td></tr>"
            f"<tr><td class=\"k\">generated_at</td><td class=\"v\">{escape(pre_generated_at)}</td><td></td></tr>"
            f"<tr><td class=\"k\">total_files</td><td class=\"v\">{_fmt_int(pre_total_files)}</td><td></td></tr>"
            f"<tr><td class=\"k\">total_size</td><td class=\"v\">{escape(_fmt_bytes(pre_total_bytes))}</td><td></td></tr>"
            f"<tr><td class=\"k\">pdf_scan (scanned/text/unknown)</td><td class=\"v\">{_fmt_int(pre_pdf_scanned)}/{_fmt_int(pre_pdf_text)}/{_fmt_int(pre_pdf_unknown)}</td><td></td></tr>"
            + TABLE_TBODY_CLOSE
        )
        precheck_section = (
            "<div class=\"section\">"
            "<h2>Precheck（入库前摸底）</h2>"
            "<div class=\"two\">"
            f"<div><h2>概览</h2>{pre_meta}</div>"
            f"<div><h2>格式分布（Top）</h2>{_render_bar_table(pre_by_type, total=max(1, pre_total_files))}</div>"
            "</div>"
            "<div class=\"two\" style=\"margin-top:12px\">"
            f"<div><h2>文件大小分布</h2>{_render_histogram(pre.get('file_size_histogram'))}</div>"
            f"<div><h2>长度分布（tokens）</h2>{_render_histogram(pre.get('token_histogram'))}</div>"
            "</div>"
            "<div class=\"two\" style=\"margin-top:12px\">"
            f"<div><h2>语言分布（抽样）</h2>{_render_bar_table(pre_lang, total=max(1, pre_total_files))}</div>"
            f"<div><h2>问题清单（可操作）</h2>{_render_bar_table(pre_finding_rows[:12], total=max(1, pre_total_files))}</div>"
            "</div>"
            "<div class=\"two\" style=\"margin-top:12px\">"
            f"<div><h2>PII 命中（次数）</h2>{_render_bar_table(pre_pii, total=max(1, sum(v for _, v in pre_pii) if pre_pii else 1))}</div>"
            f"<div><h2>Secrets/Token 命中（次数）</h2>{_render_bar_table(pre_secrets, total=max(1, sum(v for _, v in pre_secrets) if pre_secrets else 1))}</div>"
            "</div>"
            "<div style=\"margin-top:12px\">"
            f"<h2>目录结构（Top 风险聚集区）</h2>{_render_pre_dir_table(pre.get('directory_stats'), max_rows=20)}"
            "</div>"
            "</div>"
        )

    kg = report.get("kg_stats") if isinstance(report, dict) else None
    kgd = kg if isinstance(kg, dict) else {}
    kg_events = int(kgd.get("events") or 0)
    kg_entities = int(kgd.get("entities") or 0)
    kg_links = int(kgd.get("links") or 0)
    kg_events_with_chunk = int(kgd.get("events_with_chunk_id") or 0)
    kg_events_with_page = int(kgd.get("events_with_page_ref") or 0)
    kg_links_with_prov = int(kgd.get("links_with_provenance") or 0)
    kg_links_with_page = int(kgd.get("links_with_page_ref") or 0)
    kg_docs_extracted = int(kgd.get("documents_with_kg_extracted_at") or 0)
    kg_docs_with_events = int(kgd.get("documents_with_kg_events") or 0)
    kg_event_count_from_docs = int(kgd.get("event_count_from_documents") or 0)
    kg_skipped_chunks = int(kgd.get("skipped_chunks_total") or 0)
    kg_skipped_short = int(kgd.get("skipped_short_chunks_total") or 0)
    kg_failed_chunks = int(kgd.get("failed_chunks_total") or 0)
    kg_retry_chunks = int(kgd.get("retry_chunks_total") or 0)
    kg_updated_at = str(kgd.get("updated_at") or "").strip()
    kg_types: list[tuple[str, int]] = []
    raw_types = kgd.get("entity_types")
    if isinstance(raw_types, list):
        for t in raw_types[:50]:
            if not isinstance(t, dict):
                continue
            tp = str(t.get("type") or "").strip() or "unknown"
            try:
                cnt = int(t.get("count") or 0)
            except Exception:
                cnt = 0
            if cnt > 0:
                kg_types.append((tp, cnt))

    kg_top_docs = kgd.get("top_documents") if isinstance(kgd.get("top_documents"), list) else []
    kg_doc_rows: list[str] = []
    if not redact and isinstance(kg_top_docs, list):
        for r in kg_top_docs[:10]:
            if not isinstance(r, dict):
                continue
            did = str(r.get("document_id") or "").strip()
            if not did:
                continue
            src = str(r.get("source") or "").strip()
            try:
                evc = int(r.get("event_count") or 0)
            except Exception:
                evc = 0
            kg_doc_rows.append(
                "<tr>"
                f"<td class=\\\"k\\\">{escape(src or did[:8])}</td>"
                f"<td class=\\\"v\\\">{_fmt_int(evc)}</td>"
                "<td></td>"
                "</tr>"
            )
    kg_top_docs_table = (
        "<table class=\\\"bars\\\"><thead><tr><th>doc</th><th>events</th><th></th></tr></thead><tbody>"
        + "".join(kg_doc_rows)
        + TABLE_TBODY_CLOSE
        if kg_doc_rows
        else EMPTY_DATA_DIV
    )

    rr = report.get("latest_regression_run") if isinstance(report, dict) else None
    rrd = rr if isinstance(rr, dict) else {}
    rr_status = str(rrd.get("status") or "").strip()
    rr_created_at = str(rrd.get("created_at") or "").strip()
    rr_finished_at = str(rrd.get("finished_at") or "").strip()
    rr_summary = rrd.get("summary") if isinstance(rrd.get("summary"), dict) else {}
    rr_summary_items: list[tuple[str, str]] = []
    for k, v in sorted(rr_summary.items(), key=lambda kv: str(kv[0] or "")):
        key = str(k or "").strip()
        if not key:
            continue
        if isinstance(v, bool):
            rr_summary_items.append((key, "1" if v else "0"))
        elif isinstance(v, int) and not isinstance(v, bool):
            rr_summary_items.append((key, _fmt_int(v)))
        elif isinstance(v, float):
            rr_summary_items.append((key, f"{v:.4f}"))

    rr_summary_rows = [f"<tr><td class=\"k\">{escape(k)}</td><td class=\"v\">{escape(v)}</td><td></td></tr>" for k, v in rr_summary_items[:50]]
    rr_summary_table = (
        BARS_METRIC_TABLE_HEADER
        + "".join(rr_summary_rows)
        + TABLE_TBODY_CLOSE
        if rr_summary_rows
        else EMPTY_DATA_DIV
    )

    rr_slices = rr_summary.get("retrieval_slices") if isinstance(rr_summary.get("retrieval_slices"), dict) else {}

    def _fmt_num(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, bool):
            return "1" if v else "0"
        if isinstance(v, int) and not isinstance(v, bool):
            return _fmt_int(v)
        if isinstance(v, float):
            return f"{v:.4f}"
        return str(v)

    def _render_rr_slice_table(dim: str) -> str:
        if redact and dim == "directory":
            return '<div class="empty">已脱敏：directory 不展示</div>'
        obj = rr_slices.get(dim) if isinstance(rr_slices.get(dim), dict) else {}
        buckets = obj.get("buckets") if isinstance(obj.get("buckets"), list) else []
        rows: list[str] = []
        for b in buckets[:10]:
            if not isinstance(b, dict):
                continue
            key = str(b.get("key") or "").strip()
            if not key:
                continue
            try:
                items = int(b.get("items") or 0)
            except Exception:
                items = 0
            rows.append(
                "<tr>"
                f"<td class=\\\"k\\\">{escape(key)}</td>"
                f"<td class=\\\"v\\\">{_fmt_int(items)}</td>"
                f"<td class=\\\"v\\\">{escape(_fmt_num(b.get('retrieval_recall')))}</td>"
                f"<td class=\\\"v\\\">{escape(_fmt_num(b.get('retrieval_hit_at_20')))}</td>"
                f"<td class=\\\"v\\\">{escape(_fmt_num(b.get('retrieval_mrr')))}</td>"
                f"<td class=\\\"v\\\">{escape(_fmt_num(b.get('abstain_rate')))}</td>"
                "</tr>"
            )
        return (
            "<table class=\\\"bars\\\"><thead><tr><th>bucket</th><th>items</th><th>recall</th><th>hit@20</th><th>mrr</th><th>abstain</th></tr></thead><tbody>"
            + "".join(rows)
            + TABLE_TBODY_CLOSE
            if rows
            else '<div class=\"empty\">暂无数据</div>'
        )

    rr_slices_section = ""
    if rr_slices:
        rr_slices_section = (
            "<div class=\\\"section\\\">"
            "<h2>Retrieval Slices（file_type / language / directory）</h2>"
            "<div class=\\\"two\\\">"
            f"<div><h2>file_type</h2>{_render_rr_slice_table('file_type')}</div>"
            f"<div><h2>language</h2>{_render_rr_slice_table('language')}</div>"
            "</div>"
            "<div style=\\\"margin-top:12px\\\"><h2>directory</h2>"
            f"{_render_rr_slice_table('directory')}"
            "</div>"
            "</div>"
        )

    retrieval_audit_section = _render_retrieval_audit_section(report)
    raw_report = _report_with_safe_retrieval_audit(report)
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

	    <div class="section two">
	      <div>
	        <h2>状态分布</h2>
	        {_render_bar_table(by_status, total=max(1, total_docs))}
	      </div>
	      <div>
	        <h2>格式分布（Top）</h2>
	        {_render_bar_table(by_type, total=max(1, total_docs))}
	      </div>
	    </div>

		    <div class="section two">
		      <div>
		        <h2>长度分布（chars）</h2>
		        {_render_histogram(prof.get("length_histogram"))}
	      </div>
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
    name = REDACTED_TEXT if redact else (dataset_name or "")
    dsid = REDACTED_TEXT if redact else (dataset_id or "")
    rp = REDACTED_TEXT if redact else (root_path or "")
    ts = generated_at.isoformat() if isinstance(generated_at, datetime) else (str(generated_at or "") or "")

    total_files = int(summary.get("total_files") or 0)
    total_bytes = int(summary.get("total_size_bytes") or 0)
    p50 = int(((summary.get("length_percentiles") or {}) if isinstance(summary.get("length_percentiles"), dict) else {}).get("p50") or 0)
    p90 = int(((summary.get("length_percentiles") or {}) if isinstance(summary.get("length_percentiles"), dict) else {}).get("p90") or 0)
    tok_p50 = int(((summary.get("token_percentiles") or {}) if isinstance(summary.get("token_percentiles"), dict) else {}).get("p50") or 0)
    tok_p90 = int(((summary.get("token_percentiles") or {}) if isinstance(summary.get("token_percentiles"), dict) else {}).get("p90") or 0)

    pdf = summary.get("pdf_scan") if isinstance(summary.get("pdf_scan"), dict) else {}
    pdf_scanned = int(pdf.get("scanned") or 0)
    pdf_text = int(pdf.get("not_scanned") or 0)
    pdf_unknown = int(pdf.get("unknown") or 0)

    by_type = _as_items(summary.get("by_file_type"), top=12)
    lang = _as_items(summary.get("language_mix"), top=4)
    pii = _as_items(summary.get("pii_hits_total"), top=12)
    secrets = _as_items(summary.get("secrets_hits_total"), top=12)
    primary_tags = _as_items(summary.get("primary_tag_counts"), top=12)
    processing_paths = _as_items(summary.get("processing_path_counts"), top=12)

    # Best-effort actionable suggestions (objective signals only).
    findings = summary.get("findings") if isinstance(summary.get("findings"), list) else []
    finding_counts: dict[str, int] = {}
    for f in findings:
        if not isinstance(f, dict):
            continue
        k = str(f.get("key") or "").strip().lower()
        if not k:
            continue
        try:
            finding_counts[k] = int(f.get("count") or 0)
        except Exception:
            finding_counts[k] = 0

    tips: list[str] = []
    if int(pdf_scanned) > 0:
        tips.append(f"检测到疑似扫描 PDF：{_fmt_int(pdf_scanned)}（建议启用 OCR 解析链路，并优先复核 pdf_unknown/低密度页面）")
    if int(finding_counts.get("gibberish_text", 0) or 0) > 0:
        tips.append("检测到疑似乱码/编码问题（抽样信号）：建议检查源文件编码、解析器后备策略，并优先启用治理低密度过滤/隔离")
    if int(finding_counts.get("empty_text", 0) or 0) > 0:
        tips.append("存在“未提取到文本”的文件：若这些文件需要入库，建议调整解析/路由（PDF 走 OCR、二进制先转换）")
    if int(tok_p90) > 0:
        if int(tok_p90) >= 20_000:
            tips.append(f"P90 文本长度较长（~{_fmt_int(tok_p90)} tokens）：建议提高 chunk_size 或使用结构化 chunk_strategy（markdown_header/outline），入库后用 chunk-preview + gate 验证分布")
        elif int(tok_p90) >= 5_000:
            tips.append(f"P90 文本长度偏长（~{_fmt_int(tok_p90)} tokens）：建议检查 chunk_size/overlap，避免 chunk 数过多导致成本/延迟上升")
    elif int(p90) > 0:
        tips.append("tokens 分布为空（可能未启用文本抽取或文件类型非文本）；如需成本估算，建议开启 enable_text_extract 并重跑预检")
    if pii:
        tips.append("检测到 PII 命中（来自抽样/治理信号）：建议启用治理脱敏/隔离规则（governance_pii_*）并人工复核样本")
    if secrets:
        tips.append("检测到 Secrets/Token 命中（来自抽样/治理信号）：建议启用 secrets 脱敏/隔离（governance_secrets_*）并人工复核样本")
    if not tips:
        tips.append("暂无显著风险信号；建议先用 chunk-preview 小样本调参，再进行小批量入库验证（可回归）")

    tips_html = (
        "<div class=\"notes\"><ul>" + "".join(f"<li>{escape(t)}</li>" for t in tips) + "</ul></div>"
        if tips
        else EMPTY_BRIEF_DIV
    )

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

    pdf_det = summary.get("pdf_detection") if isinstance(summary.get("pdf_detection"), dict) else {}

    def _render_dir_table(items: Any, *, max_rows: int = 20) -> str:
        if redact:
            return '<div class="empty">已脱敏：目录结构不展示</div>'
        if not isinstance(items, list) or not items:
            return EMPTY_DATA_DIV
        rows: list[str] = []
        for obj in items[: max(0, int(max_rows))]:
            if not isinstance(obj, dict):
                continue
            path = escape(str(obj.get("path") or "."))
            total_files = int(obj.get("total_files") or 0)
            risky_files = int(obj.get("risky_files") or 0)
            size_bytes = _fmt_bytes(obj.get("total_size_bytes") or 0)
            rows.append(
                "<tr>"
                f"<td class=\"k\">{path}</td>"
                f"<td class=\"v\">{_fmt_int(risky_files)}/{_fmt_int(total_files)}</td>"
                f"<td class=\"v\">{escape(size_bytes)}</td>"
                "</tr>"
            )
        if not rows:
            return EMPTY_DATA_DIV
        return (
            "<table class=\"bars\">"
            "<thead><tr><th>Directory</th><th>Risky/Total</th><th>Bytes</th></tr></thead>"
            "<tbody>"
            + "".join(rows)
            + TABLE_TBODY_CLOSE
        )

    # Optional representative sampling section.
    samples_section = ""
    if isinstance(samples, dict) and samples:
        rep = samples.get("representative") if isinstance(samples.get("representative"), list) else []
        needs_review = samples.get("needs_review") if isinstance(samples.get("needs_review"), dict) else {}

        def _render_file_list(items: Any, *, max_rows: int = 60) -> str:
            if not isinstance(items, list) or not items:
                return EMPTY_BRIEF_DIV
            rows: list[str] = []
            for obj in items[: max(0, int(max_rows))]:
                if not isinstance(obj, dict):
                    continue
                nm = escape(str(obj.get("name") or ""))
                ft = escape(str(obj.get("file_type") or ""))
                sz = _fmt_bytes(obj.get("file_size"))
                rows.append(f"<tr><td class=\"k\">{nm}</td><td class=\"v\">{ft}</td><td class=\"v\">{escape(sz)}</td></tr>")
            if not rows:
                return EMPTY_BRIEF_DIV
            return (
                "<table class=\"bars\">"
                "<thead><tr><th>File</th><th>Type</th><th>Size</th></tr></thead>"
                "<tbody>"
                + "".join(rows)
                + TABLE_TBODY_CLOSE
            )

        # Needs-review overview (per bucket).
        needs_rows: list[str] = []
        for k, lst in sorted(needs_review.items(), key=lambda kv: str(kv[0] or "")):
            if not isinstance(lst, list) or not lst:
                continue
            label = escape(str(k))
            needs_rows.append(f"<tr><td class=\"k\">{label}</td><td class=\"v\">{_fmt_int(len(lst))}</td></tr>")
        needs_table = (
            "<table class=\"bars\">"
            "<thead><tr><th>Bucket</th><th>Samples</th></tr></thead>"
            "<tbody>"
            + "".join(needs_rows)
            + TABLE_TBODY_CLOSE
            if needs_rows
            else EMPTY_BRIEF_DIV
        )

        samples_section = (
            "<div class=\"section two\">"
            "<div>"
            "<h2>代表性样本（按格式/大小/PDF类型分层）</h2>"
            + _render_file_list(rep, max_rows=60)
            + "</div>"
            "<div>"
            "<h2>需复核样本（按问题分桶）</h2>"
            + needs_table
            + "</div>"
            "</div>"
        )

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
      {_render_dir_table(summary.get("directory_stats"), max_rows=20)}
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
