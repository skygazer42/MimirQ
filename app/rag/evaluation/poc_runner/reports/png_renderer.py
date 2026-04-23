from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw


def render_dataset_analysis_png(report: dict[str, Any]) -> bytes:
    width = 1400
    height = 1360
    image = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)

    y = 24
    title = str(((report.get("meta") or {}).get("dataset_name")) or ((report.get("meta") or {}).get("dataset_id")) or "Dataset Analysis")
    draw.text((24, y), title, fill=(17, 24, 39))
    y += 36
    draw.text((24, y), f"generated_at: {((report.get('meta') or {}).get('generated_at') or '')}", fill=(75, 85, 99))
    y += 40

    draw.text((24, y), "Metrics", fill=(17, 24, 39))
    y += 28
    for key, value in dict(report.get("metrics") or {}).items():
        draw.text((32, y), f"{key}: {value}", fill=(31, 41, 55))
        y += 24

    y += 12
    draw.text((24, y), "Counts", fill=(17, 24, 39))
    y += 28
    for key, value in dict(report.get("counts") or {}).items():
        draw.text((32, y), f"{key}: {value}", fill=(31, 41, 55))
        y += 24

    y += 16
    draw.text((24, y), "Top Examples", fill=(17, 24, 39))
    y += 28
    for category, rows in dict(report.get("top_examples") or {}).items():
        draw.text((32, y), str(category), fill=(17, 24, 39))
        y += 24
        for row in list(rows or [])[:3]:
            draw.text(
                (48, y),
                f"{row.get('interaction_id')}: {str(row.get('original_query') or '')[:110]}",
                fill=(55, 65, 81),
            )
            y += 22
        y += 10

    y += 16
    draw.text((24, y), "Coverage Heatmap", fill=(17, 24, 39))
    y += 30

    heatmap_rows = list((report.get("coverage_heatmap") or {}).get("rows") or [])
    cell_x = 360
    base_x = 24
    bar_width = 220
    row_height = 30
    draw.text((base_x, y - 22), "filename", fill=(107, 114, 128))
    draw.text((cell_x, y - 22), "retrieval", fill=(107, 114, 128))
    draw.text((cell_x + bar_width + 80, y - 22), "negative", fill=(107, 114, 128))

    max_retrieval = max([int(row.get("retrieval_hit_count") or 0) for row in heatmap_rows] or [1])
    max_negative = max([int(row.get("negative_feedback_count") or 0) for row in heatmap_rows] or [1])
    for row in heatmap_rows[:12]:
        filename = str(row.get("filename") or "")
        retrieval = int(row.get("retrieval_hit_count") or 0)
        negative = int(row.get("negative_feedback_count") or 0)
        draw.text((base_x, y), filename[:42], fill=(31, 41, 55))
        draw.rectangle(
            (cell_x, y + 4, cell_x + int((retrieval / max_retrieval) * bar_width), y + 18),
            fill=(59, 130, 246),
        )
        draw.text((cell_x + bar_width + 12, y), str(retrieval), fill=(31, 41, 55))
        draw.rectangle(
            (cell_x + bar_width + 80, y + 4, cell_x + bar_width + 80 + int((negative / max_negative) * bar_width), y + 18),
            fill=(239, 68, 68),
        )
        draw.text((cell_x + bar_width * 2 + 92, y), str(negative), fill=(31, 41, 55))
        y += row_height

    y += 28
    draw.text((24, y), "UMAP Scatter", fill=(17, 24, 39))
    y += 16
    scatter_points = list((report.get("umap_scatter") or {}).get("points") or [])
    chart_left = 24
    chart_top = y + 12
    chart_width = 980
    chart_height = 240
    draw.rounded_rectangle(
        (chart_left, chart_top, chart_left + chart_width, chart_top + chart_height),
        radius=18,
        outline=(203, 213, 225),
        width=2,
        fill=(248, 250, 252),
    )
    if scatter_points:
        xs = [float(point.get("x") or 0.0) for point in scatter_points]
        ys = [float(point.get("y") or 0.0) for point in scatter_points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 1e-6)
        span_y = max(max_y - min_y, 1e-6)
        color_map = {
            "document": (37, 99, 235),
            "query": (100, 116, 139),
            "out_of_scope_candidate": (220, 38, 38),
        }
        for point in scatter_points[:80]:
            x = float(point.get("x") or 0.0)
            yy = float(point.get("y") or 0.0)
            cx = chart_left + 28 + int(((x - min_x) / span_x) * (chart_width - 56))
            cy = chart_top + 24 + int(((max_y - yy) / span_y) * (chart_height - 48))
            color = color_map.get(str(point.get("group") or ""), (15, 23, 42))
            radius = 6 if str(point.get("kind") or "") == "document" else 5
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color)
            if str(point.get("group") or "") == "out_of_scope_candidate":
                draw.text((cx + 8, cy - 6), str(point.get("label") or "")[:20], fill=(127, 29, 29))
    else:
        draw.text((chart_left + 18, chart_top + 18), "No UMAP scatter data", fill=(100, 116, 139))

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
