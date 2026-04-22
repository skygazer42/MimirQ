from __future__ import annotations

from typing import Any


def compute_fusion_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = 0
    conflicts = 0
    gains: list[float] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        total += 1
        if bool(row.get("has_conflict")):
            conflicts += 1
        try:
            retrieval = float(row.get("retrieval_score") or 0.0)
            kg = float(row.get("kg_score") or 0.0)
            hybrid = float(row.get("hybrid_score") or 0.0)
        except Exception:
            continue
        gains.append(hybrid - max(retrieval, kg))

    conflict_rate = 0.0 if total <= 0 else round(conflicts / total, 4)
    net_gain = 0.0 if not gains else round(sum(gains) / len(gains), 4)
    return {
        "evaluated": total,
        "conflict_rate": conflict_rate,
        "net_gain_over_best_single": net_gain,
    }
