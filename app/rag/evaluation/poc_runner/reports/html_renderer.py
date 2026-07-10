
from html import escape
from typing import Any

from pyecharts import options as opts
from pyecharts.charts import HeatMap


def _render_umap_scatter(report: dict[str, Any]) -> str:
    scatter = dict(report.get("umap_scatter") or {})
    points = list(scatter.get("points") or [])
    if not points:
        return "<div id='umap-scatter'>暂无 UMAP 散点数据</div>"

    width = 920.0
    height = 420.0
    padding = 36.0
    xs = [float(point.get("x") or 0.0) for point in points]
    ys = [float(point.get("y") or 0.0) for point in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    color_map = {
        "document": "#2563eb",
        "query": "#64748b",
        "out_of_scope_candidate": "#dc2626",
    }
    circles: list[str] = []
    labels: list[str] = []
    for point in points:
        x = float(point.get("x") or 0.0)
        y = float(point.get("y") or 0.0)
        cx = padding + ((x - min_x) / span_x) * (width - padding * 2)
        cy = padding + ((max_y - y) / span_y) * (height - padding * 2)
        color = color_map.get(str(point.get("group") or ""), "#0f172a")
        radius = 6 if str(point.get("kind") or "") == "document" else 5
        circles.append(f"<circle cx='{cx:.1f}' cy='{cy:.1f}' r='{radius}' fill='{color}' fill-opacity='0.78' />")
        if str(point.get("group") or "") == "out_of_scope_candidate":
            labels.append(
                f"<text x='{cx + 8:.1f}' y='{cy - 6:.1f}' font-size='11' fill='#7f1d1d'>{escape(str(point.get('label') or '')[:24])}</text>"
            )

    legend = (
        "<div style='display:flex;gap:16px;margin-top:12px;font-size:12px'>"
        "<span><span style='display:inline-block;width:10px;height:10px;background:#2563eb;border-radius:999px'></span> document</span>"
        "<span><span style='display:inline-block;width:10px;height:10px;background:#64748b;border-radius:999px'></span> query</span>"
        "<span><span style='display:inline-block;width:10px;height:10px;background:#dc2626;border-radius:999px'></span> out_of_scope_candidate</span>"
        "</div>"
    )
    svg = (
        f"<svg viewBox='0 0 {int(width)} {int(height)}' width='100%' height='{int(height)}' role='img' aria-label='umap scatter'>"
        "<rect x='0' y='0' width='100%' height='100%' fill='#f8fafc' rx='16' />"
        + "".join(circles)
        + "".join(labels)
        + "</svg>"
    )
    return f"<div id='umap-scatter'>{svg}{legend}</div>"


def _render_latency_breakdown(report: dict[str, Any]) -> str:
    payload = dict(report.get("latency_breakdown") or {})
    summary = dict(payload.get("summary") or {})
    if not summary:
        return "<div id='latency-breakdown'>暂无延迟分解数据</div>"
    return (
        "<div id='latency-breakdown'>"
        f"<p><code>avg_wait_in_queue_ms</code>: {escape(str(summary.get('avg_wait_in_queue_ms')))}</p>"
        f"<p><code>avg_active_inference_ms</code>: {escape(str(summary.get('avg_active_inference_ms')))}</p>"
        f"<p><code>concurrency_issue_count</code>: {escape(str(summary.get('concurrency_issue_count')))}</p>"
        f"<p><code>hardware_or_model_issue_count</code>: {escape(str(summary.get('hardware_or_model_issue_count')))}</p>"
        "</div>"
    )


def _render_heatmap(report: dict[str, Any]) -> str:
    heatmap = dict(report.get("coverage_heatmap") or {})
    rows = list(heatmap.get("rows") or [])
    if not rows:
        return "<div id='coverage-heatmap'>暂无热力图数据</div>"

    x_axis = list(heatmap.get("x_axis") or [])
    y_axis = list(heatmap.get("y_axis") or [])
    x_index = {value: idx for idx, value in enumerate(x_axis)}
    y_index = {value: idx for idx, value in enumerate(y_axis)}
    values: list[list[int]] = []
    for filename, metric, value in heatmap.get("cells") or []:
        if filename not in y_index or metric not in x_index:
            continue
        values.append([x_index[metric], y_index[filename], int(value or 0)])

    chart = (
        HeatMap(init_opts=opts.InitOpts(width="980px", height=f"{max(280, 80 + len(y_axis) * 36)}px"))
        .add_xaxis(x_axis)
        .add_yaxis("coverage", y_axis, values)
        .set_global_opts(
            title_opts=opts.TitleOpts(title="coverage-heatmap"),
            toolbox_opts=opts.ToolboxOpts(is_show=False),
            visualmap_opts=opts.VisualMapOpts(min_=0, max_=max([int(v[2]) for v in values] or [1])),
            xaxis_opts=opts.AxisOpts(axislabel_opts=opts.LabelOpts(rotate=0)),
        )
    )
    return f"<div id='coverage-heatmap'>{chart.render_embed()}</div>"


def _render_metric_list(metrics: dict[str, Any]) -> str:
    items = []
    for key, value in metrics.items():
        items.append(f"<li><code>{escape(str(key))}</code>: {escape(str(value))}</li>")
    return "<ul>" + "".join(items) + "</ul>"


def _render_metric_cards(report: dict[str, Any]) -> str:
    cards = list(report.get("metric_cards") or [])
    feedback = dict(report.get("feedback_coverage") or {})
    blocks: list[str] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        blocks.append(
            "<div class='metric-card'>"
            f"<div class='metric-key'><code>{escape(str(card.get('key') or ''))}</code></div>"
            f"<div class='metric-value'>{escape(str(card.get('value')))}</div>"
            "</div>"
        )
    if feedback:
        blocks.append(
            "<div class='metric-card feedback-coverage'>"
            f"<div class='metric-key'><code>{escape(str(feedback.get('key') or ''))}</code></div>"
            f"<div class='metric-value'>{escape(str(feedback.get('value')))}</div>"
            "</div>"
        )
    return "<div id='metric-cards' class='metric-cards'>" + "".join(blocks) + "</div>"


def _render_top_examples(top_examples: dict[str, Any]) -> str:
    blocks: list[str] = []
    for category, rows in (top_examples or {}).items():
        rows = list(rows or [])
        items: list[str] = []
        for row in rows[:10]:
            items.append(
                "<li>"
                f"<strong>{escape(str(row.get('interaction_id') or ''))}</strong> "
                f"{escape(str(row.get('original_query') or ''))}"
                "</li>"
            )
        blocks.append(f"<section><h3>{escape(str(category))}</h3><ul>{''.join(items)}</ul></section>")
    return "".join(blocks) if blocks else "<div>暂无样例</div>"


def render_dataset_analysis_html(report: dict[str, Any]) -> str:
    meta = dict(report.get("meta") or {})
    dataset_name = str(meta.get("dataset_name") or meta.get("dataset_id") or "Dataset Analysis")
    generated_at = str(meta.get("generated_at") or "")
    filters = dict(meta.get("filters") or {})
    scope_summary = dict(meta.get("scope_summary") or {})
    glossary_candidates = list(report.get("glossary_candidates") or [])

    glossary_html = "".join(
        f"<li>{escape(str(item.get('token') or ''))} ({escape(str(item.get('count') or '0'))})</li>"
        for item in glossary_candidates[:10]
    ) or "<li>暂无候选</li>"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(dataset_name)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 24px; color: #111827; }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    .meta, .section {{ margin-top: 20px; }}
    .card {{ border: 1px solid #d1d5db; border-radius: 12px; padding: 16px; margin-bottom: 16px; }}
    code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 6px; }}
    .metric-cards {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
    .metric-card {{ border: 1px solid #e5e7eb; border-radius: 10px; padding: 12px; background: #f8fafc; }}
    .metric-key {{ font-size: 12px; color: #475569; margin-bottom: 8px; }}
    .metric-value {{ font-size: 22px; font-weight: 600; color: #0f172a; }}
    .feedback-coverage {{ grid-column: span 3; background: #eef6ff; }}
  </style>
</head>
<body>
  <h1>{escape(dataset_name)}</h1>
  <div class="meta">generated_at: {escape(generated_at)}</div>
  <div class="card">
    <h2>filters</h2>
    <pre>{escape(str(filters))}</pre>
  </div>
  <div class="card">
    <h2>scope_summary</h2>
    <pre>{escape(str(scope_summary))}</pre>
  </div>
  <div class="card">
    <h2>metrics</h2>
    {_render_metric_cards(report)}
    {_render_metric_list(dict(report.get("metrics") or {}))}
  </div>
  <div class="card">
    <h2>top_examples</h2>
    {_render_top_examples(dict(report.get("top_examples") or {}))}
  </div>
  <div class="card">
    <h2>manual_review_candidates</h2>
    <pre>{escape(str(report.get("manual_review_candidates") or []))}</pre>
  </div>
  <div class="card">
    <h2>glossary_candidates</h2>
    <ul>{glossary_html}</ul>
  </div>
  <div class="card section">
    <h2>umap_scatter</h2>
    {_render_umap_scatter(report)}
  </div>
  <div class="card section">
    <h2>latency_breakdown</h2>
    {_render_latency_breakdown(report)}
  </div>
  <div class="card section">
    <h2>coverage_heatmap</h2>
    {_render_heatmap(report)}
  </div>
</body>
</html>"""
