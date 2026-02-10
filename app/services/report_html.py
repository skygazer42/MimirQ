"""
HTML report rendering (single-file, offline-friendly).

Design goals:
- One self-contained HTML file (no external JS/CSS)
- Objective numbers only (no subjective scoring)
- Optional redaction for sharing (hide dataset id/name/path)
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any


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
        return '<div class="empty">暂无数据</div>'
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
        + "</tbody></table>"
    )


def _render_histogram(bins: Any) -> str:
    if not isinstance(bins, list) or not bins:
        return '<div class="empty">暂无数据</div>'
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


def render_dataset_profile_html(
    *,
    title: str,
    dataset_name: str | None,
    dataset_id: str | None,
    generated_at: datetime | str | None,
    summary: dict,
    redact: bool = False,
) -> str:
    name = "[REDACTED]" if redact else (dataset_name or "")
    dsid = "[REDACTED]" if redact else (dataset_id or "")
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

    name = "[REDACTED]" if redact else (dataset_name or "")
    dsid = "[REDACTED]" if redact else (dataset_id or "")
    ts = generated_at.isoformat() if isinstance(generated_at, datetime) else (str(generated_at or "") or "")

    profile = report.get("profile") if isinstance(report, dict) else None
    prof = profile if isinstance(profile, dict) else {}

    total_docs = int(prof.get("total_documents") or 0)
    total_bytes = int(prof.get("total_size_bytes") or 0)

    by_status = _as_items(prof.get("by_status"), top=12)
    by_type = _as_items(prof.get("by_file_type"), top=12)

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

    raw_json = json.dumps(report, ensure_ascii=False, indent=2)

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
        <h2>Chunk Quality Gate（文档数）</h2>
        {_render_bar_table(gate_grades, total=max(1, total_docs))}
      </div>
      <div>
        <h2>Chunk 风险计数（best-effort）</h2>
        {_render_bar_table([("coverage_low", coverage_low), ("overlap_waste_high", overlap_high), ("token_stats_missing", tokens_missing)], total=max(1, total_docs))}
      </div>
    </div>

    <div class="section">
      <h2>Pipeline 版本分布</h2>
      {_render_bar_table(version_items, total=max(1, total_docs))}
    </div>

    <div class="section">
      <h2>最近 Connector Runs</h2>
      {('<table class="bars"><thead><tr><th>connector_id</th><th>status</th><th>created_at</th></tr></thead><tbody>' + ''.join(conn_rows) + '</tbody></table>') if conn_rows else '<div class="empty">暂无数据</div>'}
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
    name = "[REDACTED]" if redact else (dataset_name or "")
    dsid = "[REDACTED]" if redact else (dataset_id or "")
    rp = "[REDACTED]" if redact else (root_path or "")
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
    pii = _as_items(summary.get("pii_hits_total"), top=12)
    secrets = _as_items(summary.get("secrets_hits_total"), top=12)

    # Best-effort actionable suggestions (objective signals only).
    tips: list[str] = []
    if int(pdf_scanned) > 0:
        tips.append(f"检测到疑似扫描 PDF：{_fmt_int(pdf_scanned)}（建议启用 OCR 解析链路，并优先复核 pdf_unknown/低密度页面）")
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
        else '<div class="empty">暂无</div>'
    )

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

    pdf_det = summary.get("pdf_detection") if isinstance(summary.get("pdf_detection"), dict) else {}

    # Optional representative sampling section.
    samples_section = ""
    if isinstance(samples, dict) and samples:
        rep = samples.get("representative") if isinstance(samples.get("representative"), list) else []
        needs_review = samples.get("needs_review") if isinstance(samples.get("needs_review"), dict) else {}

        def _render_file_list(items: Any, *, max_rows: int = 60) -> str:
            if not isinstance(items, list) or not items:
                return '<div class="empty">暂无</div>'
            rows: list[str] = []
            for obj in items[: max(0, int(max_rows))]:
                if not isinstance(obj, dict):
                    continue
                nm = escape(str(obj.get("name") or ""))
                ft = escape(str(obj.get("file_type") or ""))
                sz = _fmt_bytes(obj.get("file_size"))
                rows.append(f"<tr><td class=\"k\">{nm}</td><td class=\"v\">{ft}</td><td class=\"v\">{escape(sz)}</td></tr>")
            if not rows:
                return '<div class="empty">暂无</div>'
            return (
                "<table class=\"bars\">"
                "<thead><tr><th>File</th><th>Type</th><th>Size</th></tr></thead>"
                "<tbody>"
                + "".join(rows)
                + "</tbody></table>"
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
            + "</tbody></table>"
            if needs_rows
            else '<div class="empty">暂无</div>'
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
      <h2>文件大小分布</h2>
      {_render_histogram(summary.get("file_size_histogram"))}
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
