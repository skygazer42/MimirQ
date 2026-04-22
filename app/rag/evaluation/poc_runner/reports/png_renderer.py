from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw


def render_dataset_analysis_png(report: dict[str, Any]) -> bytes:
    width = 1400
    height = 1100
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

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
