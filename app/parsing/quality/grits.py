"""
Lightweight GriTS-style scoring helpers for parse benchmarks.

This is a dependency-free proxy for internal PubTables-style scoring. It
captures two signals:
- topology: whether the row/column cell layout matches
- content: whether normalized cell text matches at the same row/column slot
"""

import re
from collections import Counter
from typing import Any

_WS_RE = re.compile(r"\s+")


def _normalize_cell(cell: Any) -> str:
    return _WS_RE.sub(" ", str(cell or "")).strip().lower()


def _f1_from_counters(pred: Counter[Any], gold: Counter[Any]) -> float | None:
    pred_total = sum(pred.values())
    gold_total = sum(gold.values())
    if pred_total <= 0 and gold_total <= 0:
        return None
    if pred_total <= 0 or gold_total <= 0:
        return 0.0

    overlap = sum(min(pred[key], gold.get(key, 0)) for key in pred.keys())
    precision = float(overlap) / float(pred_total)
    recall = float(overlap) / float(gold_total)
    if precision + recall <= 0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def _round_metric(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def compute_table_grits(
    *,
    pred_table: list[list[Any]] | None,
    gold_table: list[list[Any]] | None,
) -> dict[str, float | None]:
    pred_rows = pred_table or []
    gold_rows = gold_table or []
    if not pred_rows and not gold_rows:
        return {"topology": None, "content": None, "f1": None}

    pred_topology = Counter(
        (row_idx, col_idx) for row_idx, row in enumerate(pred_rows) for col_idx, _ in enumerate(row)
    )
    gold_topology = Counter(
        (row_idx, col_idx) for row_idx, row in enumerate(gold_rows) for col_idx, _ in enumerate(row)
    )
    topology = _f1_from_counters(pred_topology, gold_topology)

    pred_content = Counter(
        (row_idx, col_idx, normalized)
        for row_idx, row in enumerate(pred_rows)
        for col_idx, cell in enumerate(row)
        for normalized in [_normalize_cell(cell)]
        if normalized
    )
    gold_content = Counter(
        (row_idx, col_idx, normalized)
        for row_idx, row in enumerate(gold_rows)
        for col_idx, cell in enumerate(row)
        for normalized in [_normalize_cell(cell)]
        if normalized
    )
    content = _f1_from_counters(pred_content, gold_content)

    components = [value for value in (topology, content) if value is not None]
    f1 = (sum(components) / float(len(components))) if components else None

    return {
        "topology": _round_metric(topology),
        "content": _round_metric(content),
        "f1": _round_metric(f1),
    }


def compute_table_collection_grits(
    *,
    pred_tables: list[list[list[Any]]] | None,
    gold_tables: list[list[list[Any]]] | None,
) -> dict[str, float | None]:
    pred_seq = pred_tables or []
    gold_seq = gold_tables or []
    if not pred_seq and not gold_seq:
        return {"topology": None, "content": None, "f1": None}

    table_count = max(len(pred_seq), len(gold_seq))
    per_table_scores = [
        compute_table_grits(
            pred_table=(pred_seq[index] if index < len(pred_seq) else []),
            gold_table=(gold_seq[index] if index < len(gold_seq) else []),
        )
        for index in range(table_count)
    ]

    def _average(key: str) -> float | None:
        values = [score[key] for score in per_table_scores if score[key] is not None]
        if not values:
            return None
        return _round_metric(sum(float(value) for value in values) / float(len(values)))

    return {
        "topology": _average("topology"),
        "content": _average("content"),
        "f1": _average("f1"),
    }


__all__ = ["compute_table_collection_grits", "compute_table_grits"]
