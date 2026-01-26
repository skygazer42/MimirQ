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
from typing import Any, Iterable


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

    pdf = summary.get("pdf_scan") if isinstance(summary.get("pdf_scan"), dict) else {}
    pdf_scanned = int(pdf.get("scanned") or 0)
    pdf_text = int(pdf.get("not_scanned") or 0)
    pdf_unknown = int(pdf.get("unknown") or 0)

    by_type = _as_items(summary.get("by_file_type"), top=12)
    by_status = _as_items(summary.get("by_status"), top=12)
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


def render_precheck_html(
    *,
    title: str,
    dataset_name: str | None,
    dataset_id: str | None,
    root_path: str | None,
    generated_at: datetime | str | None,
    summary: dict,
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

    pdf = summary.get("pdf_scan") if isinstance(summary.get("pdf_scan"), dict) else {}
    pdf_scanned = int(pdf.get("scanned") or 0)
    pdf_text = int(pdf.get("not_scanned") or 0)
    pdf_unknown = int(pdf.get("unknown") or 0)

    by_type = _as_items(summary.get("by_file_type"), top=12)
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
        <h2>文件大小分布</h2>
        {_render_histogram(summary.get("file_size_histogram"))}
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

    <div class="footer">
      <div>说明：预检扫描以“入库前摸底”为目标，输出客观统计与待复核清单；不做主观评分。</div>
    </div>
  </div>
</body>
</html>
"""
    return html

