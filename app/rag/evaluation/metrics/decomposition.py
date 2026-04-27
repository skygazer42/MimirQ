from __future__ import annotations

import re
from typing import Any

_SPACE_RE = re.compile(r"\s+")
_EDGE_STRIP = " \t\r\n,.;:!?，。；：！？、\"'`“”‘’()（）[]【】"


def _normalize_subquery(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = _SPACE_RE.sub(" ", text)
    return text.strip(_EDGE_STRIP)


def _normalize_subquery_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _normalize_subquery(item)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def compute_decomposition_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = 0
    exact_match = 0
    precision_values: list[float] = []
    recall_values: list[float] = []
    f1_values: list[float] = []

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        gold = _normalize_subquery_list(row.get("gold_subqueries"))
        if not gold:
            continue
        predicted = _normalize_subquery_list(row.get("predicted_subqueries"))

        gold_set = set(gold)
        pred_set = set(predicted)
        evaluated += 1
        if pred_set == gold_set:
            exact_match += 1

        true_positive = int(len(gold_set & pred_set))
        precision_i = 0.0 if not pred_set else true_positive / len(pred_set)
        recall_i = 0.0 if not gold_set else true_positive / len(gold_set)
        if precision_i <= 0.0 or recall_i <= 0.0:
            f1_i = 0.0
        else:
            f1_i = (2.0 * precision_i * recall_i) / (precision_i + recall_i)

        precision_values.append(float(precision_i))
        recall_values.append(float(recall_i))
        f1_values.append(float(f1_i))

    precision = 0.0 if not precision_values else round(sum(precision_values) / len(precision_values), 4)
    recall = 0.0 if not recall_values else round(sum(recall_values) / len(recall_values), 4)
    f1 = 0.0 if not f1_values else round(sum(f1_values) / len(f1_values), 4)
    exact_match_rate = 0.0 if evaluated <= 0 else round(exact_match / evaluated, 4)

    return {
        "evaluated": int(evaluated),
        "exact_match": int(exact_match),
        "exact_match_rate": exact_match_rate,
        "precision": precision,
        "recall": recall,
        "decomposition_f1": f1,
    }


__all__ = ["compute_decomposition_metrics"]
