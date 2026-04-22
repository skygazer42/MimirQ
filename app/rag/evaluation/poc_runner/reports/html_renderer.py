from __future__ import annotations

from html import escape
from typing import Any

from pyecharts import options as opts
from pyecharts.charts import HeatMap


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
    <h2>coverage_heatmap</h2>
    {_render_heatmap(report)}
  </div>
</body>
</html>"""
