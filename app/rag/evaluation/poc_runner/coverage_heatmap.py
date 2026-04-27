from __future__ import annotations

from collections import Counter
from typing import Any


def build_document_heatmap(rows: list[dict[str, Any]]) -> dict[str, Any]:
    retrieval_counts: Counter[str] = Counter()
    negative_counts: Counter[str] = Counter()

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        filenames = [str(name or "").strip() for name in (row.get("final_context_filenames") or []) if str(name or "").strip()]
        is_negative = str(row.get("feedback_polarity") or "").strip().lower() == "negative"
        for filename in filenames:
            retrieval_counts[filename] += 1
            if is_negative:
                negative_counts[filename] += 1

    all_files = sorted(
        set(retrieval_counts.keys()) | set(negative_counts.keys()),
        key=lambda name: (-retrieval_counts.get(name, 0), -negative_counts.get(name, 0), name),
    )
    rows_out = [
        {
            "filename": filename,
            "retrieval_hit_count": int(retrieval_counts.get(filename, 0)),
            "negative_feedback_count": int(negative_counts.get(filename, 0)),
        }
        for filename in all_files
    ]
    x_axis = ["retrieval_hit_count", "negative_feedback_count"]
    y_axis = [row["filename"] for row in rows_out]
    cells: list[list[Any]] = []
    for row in rows_out:
        cells.append([row["filename"], "retrieval_hit_count", row["retrieval_hit_count"]])
        cells.append([row["filename"], "negative_feedback_count", row["negative_feedback_count"]])

    return {
        "x_axis": x_axis,
        "y_axis": y_axis,
        "rows": rows_out,
        "cells": cells,
    }
