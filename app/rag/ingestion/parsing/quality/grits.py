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
    if cell is None:
        return ""
    return _WS_RE.sub(" ", str(cell)).strip().lower()


def _f1_from_counters(pred: Counter[Any], gold: Counter[Any]) -> float | None:
    pred_total = sum(pred.values())
    gold_total = sum(gold.values())
    if pred_total <= 0 and gold_total <= 0:
        return None
    if pred_total <= 0 or gold_total <= 0:
        return 0.0

    overlap = sum(min(count, gold[key]) for key, count in pred.items())
    precision = overlap / pred_total
    recall = overlap / gold_total
    if precision + recall <= 0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def _round_metric(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 4)


def compute_table_grits(
    *,
    pred_table: list[list[Any]] | None,
    gold_table: list[list[Any]] | None,
) -> dict[str, float | None]:
    pred_rows = [] if pred_table is None else pred_table
    gold_rows = [] if gold_table is None else gold_table
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
    f1 = sum(components) / len(components) if components else None

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
    pred_seq = [] if pred_tables is None else pred_tables
    gold_seq = [] if gold_tables is None else gold_tables
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
        return _round_metric(sum(values) / len(values))

    return {
        "topology": _average("topology"),
        "content": _average("content"),
        "f1": _average("f1"),
    }


__all__ = ["compute_table_collection_grits", "compute_table_grits"]
