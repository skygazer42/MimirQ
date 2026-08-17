"""
Regression run diff HTML exporter.

Goal: produce a shareable, offline-friendly HTML artifact for before/after comparisons.
"""


import json
from datetime import datetime
from html import escape
from typing import Any


def _fmt_num(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def _render_table_or_empty(*, headers: str, rows: list[str]) -> str:
    if not rows:
        return '<div class="empty">暂无数据</div>'
    return f'<table class="bars"><thead>{headers}</thead><tbody>{"".join(rows)}</tbody></table>'


def _metric_rows(metric_diffs: list[Any]) -> list[str]:
    rows: list[str] = []
    for diff in metric_diffs[:60]:
        if not isinstance(diff, dict):
            continue
        key = str(diff.get("key") or "").strip()
        if not key:
            continue
        rows.append(
            "<tr>"
            f'<td class="k">{escape(key)}</td>'
            f'<td class="v">{escape(_fmt_num(diff.get("before")))}</td>'
            f'<td class="v">{escape(_fmt_num(diff.get("after")))}</td>'
            f'<td class="v">{escape(_fmt_num(diff.get("delta")))}</td>'
            "</tr>"
        )
    return rows


def _render_diff_score_section(diff_score: dict[str, Any]) -> str:
    score_version = str(diff_score.get("version") or "")
    if not score_version:
        return ""
    used_keys = diff_score.get("used_metric_keys") if isinstance(diff_score.get("used_metric_keys"), list) else []
    used_keys_str = ", ".join([str(key) for key in used_keys if str(key).strip()][:10])
    subtitle = (
        f'version: <span style="font-family:var(--mono)">{escape(score_version)}</span>'
        + (f' · metrics: <span style="font-family:var(--mono)">{escape(used_keys_str)}</span>' if used_keys_str else "")
    )
    return (
        '<div class="section">'
        "<h2>Diff Score (compact)</h2>"
        f'<div class="sub">{subtitle}</div>'
        '<table class="bars"><thead><tr><th>base</th><th>target</th><th>delta</th></tr></thead><tbody>'
        "<tr>"
        f'<td class="v">{escape(_fmt_num(diff_score.get("base_score")))}</td>'
        f'<td class="v">{escape(_fmt_num(diff_score.get("target_score")))}</td>'
        f'<td class="v">{escape(_fmt_num(diff_score.get("delta")))}</td>'
        "</tr>"
        "</tbody></table>"
        "</div>"
    )


def _slice_metric_map(bucket: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for metric in bucket.get("metrics") if isinstance(bucket.get("metrics"), list) else []:
        if not isinstance(metric, dict):
            continue
        key = str(metric.get("key") or "").strip()
        if key:
            out[key] = metric
    return out


def _slice_metric_cell(metrics_by_key: dict[str, dict[str, Any]], key: str) -> str:
    metric = metrics_by_key.get(key) or {}
    before = _fmt_num(metric.get("before"))
    after = _fmt_num(metric.get("after"))
    delta = _fmt_num(metric.get("delta"))
    return f"{escape(before)} → {escape(after)} (Δ {escape(delta)})"


def _slice_table_rows(buckets: list[Any]) -> list[str]:
    rows: list[str] = []
    for bucket in buckets[:30]:
        if not isinstance(bucket, dict):
            continue
        key = str(bucket.get("key") or "").strip()
        if not key:
            continue
        metrics_by_key = _slice_metric_map(bucket)
        try:
            items_before = int(bucket.get("items_before") or 0)
        except Exception:
            items_before = 0
        try:
            items_after = int(bucket.get("items_after") or 0)
        except Exception:
            items_after = 0
        rows.append(
            "<tr>"
            f'<td class="k">{escape(key)}</td>'
            f'<td class="v">{escape(str(items_before))} → {escape(str(items_after))}</td>'
            f'<td class="v">{_slice_metric_cell(metrics_by_key, "retrieval_recall")}</td>'
            f'<td class="v">{_slice_metric_cell(metrics_by_key, "retrieval_hit_at_20")}</td>'
            f'<td class="v">{_slice_metric_cell(metrics_by_key, "retrieval_mrr")}</td>'
            f'<td class="v">{_slice_metric_cell(metrics_by_key, "abstain_rate")}</td>'
            "</tr>"
        )
    return rows


def _render_slice_table(slice_diffs: dict[str, Any], dim: str) -> str:
    slice_diff = slice_diffs.get(dim) if isinstance(slice_diffs.get(dim), dict) else {}
    buckets = slice_diff.get("buckets") if isinstance(slice_diff.get("buckets"), list) else []
    return _render_table_or_empty(
        headers="<tr><th>bucket</th><th>items</th><th>recall</th><th>hit@20</th><th>mrr</th><th>abstain</th></tr>",
        rows=_slice_table_rows(buckets),
    )


def render_regression_run_diff_html(
    *,
    title: str,
    base_run_id: str,
    target_run_id: str,
    generated_at: datetime | str | None,
    diff: dict[str, Any],
    redact: bool = False,
) -> str:
    ts = generated_at.isoformat() if isinstance(generated_at, datetime) else (str(generated_at or "") or "")

    safe_base = "[REDACTED]" if redact else str(base_run_id or "")
    safe_target = "[REDACTED]" if redact else str(target_run_id or "")

    diff_score = diff.get("diff_score") if isinstance(diff.get("diff_score"), dict) else {}
    score_section = _render_diff_score_section(diff_score)

    metric_diffs = diff.get("metric_diffs") if isinstance(diff.get("metric_diffs"), list) else []
    metric_table = _render_table_or_empty(
        headers="<tr><th>metric</th><th>before</th><th>after</th><th>delta</th></tr>",
        rows=_metric_rows(metric_diffs),
    )

    slice_diffs = diff.get("slice_diffs") if isinstance(diff.get("slice_diffs"), dict) else {}
    slice_sections = "".join(
        f'<div class="section"><h2>Slice · {escape(dim)}</h2>{_render_slice_table(slice_diffs, dim)}</div>'
        for dim in ("file_type", "language", "directory")
    )

    raw_json = escape(json.dumps(diff, ensure_ascii=False, indent=2, default=str))

    return f"""<!doctype html>
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
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      --sans: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
    }}
    body {{ margin: 0; background: radial-gradient(1200px 800px at 10% 10%, rgba(56,189,248,.16), transparent), var(--bg); color: var(--text); font-family: var(--sans); }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 28px 18px 40px; }}
    .title {{ font-size: 22px; font-weight: 800; letter-spacing: .2px; }}
    .sub {{ margin-top: 6px; color: var(--muted); font-size: 13px; }}
    .section {{ margin-top: 16px; border: 1px solid var(--border); border-radius: 14px; background: rgba(0,0,0,.12); padding: 14px 14px; }}
    .section h2 {{ margin: 0 0 10px; font-size: 14px; letter-spacing: .2px; }}
    .empty {{ color: var(--muted); font-size: 13px; padding: 18px 0; text-align: center; }}
    table.bars {{ width: 100%; border-collapse: collapse; }}
    table.bars th {{ text-align: left; font-size: 12px; color: var(--muted); font-family: var(--mono); padding: 8px 6px; border-bottom: 1px solid var(--border); }}
    table.bars td {{ padding: 7px 6px; border-bottom: 1px solid rgba(255,255,255,.06); vertical-align: middle; }}
    table.bars td.k {{ font-family: var(--mono); font-size: 12px; color: var(--text); max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    table.bars td.v {{ font-family: var(--mono); font-size: 12px; color: var(--muted); }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: rgba(0,0,0,.22); padding: 12px; border: 1px solid rgba(255,255,255,.08); border-radius: 12px; font-family: var(--mono); font-size: 12px; color: var(--text); }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="title">{escape(title)}</div>
    <div class="sub">base: <span style="font-family:var(--mono)">{escape(safe_base)}</span> · target: <span style="font-family:var(--mono)">{escape(safe_target)}</span> · generated_at: <span style="font-family:var(--mono)">{escape(ts)}</span></div>

    {score_section}

    <div class="section">
      <h2>Top Metric Diffs</h2>
      {metric_table}
    </div>

    {slice_sections}

    <div class="section">
      <h2>Raw JSON（用于审计/分享）</h2>
      <pre>{raw_json}</pre>
    </div>
  </div>
</body>
</html>
"""


__all__ = ["render_regression_run_diff_html"]
