from __future__ import annotations

from typing import Any


def _to_float(value: Any) -> float:
    try:
        if value is None or isinstance(value, bool):
            return 0.0
        num = float(value)
        if num != num:
            return 0.0
        return num
    except (TypeError, ValueError):
        return 0.0


def summarize_graphrag_bench(rows: list[dict[str, Any]]) -> dict[str, Any]:
    systems: dict[str, dict[str, float]] = {}
    for row in rows or []:
        system = str((row or {}).get("system") or "").strip()
        if not system:
            continue
        recall = _to_float((row or {}).get("recall"))
        cost_usd = _to_float((row or {}).get("cost_usd"))
        latency_ms = _to_float((row or {}).get("latency_ms"))
        systems[system] = {
            "recall": round(recall, 4),
            "cost_usd": round(cost_usd, 6),
            "latency_ms": round(latency_ms, 4),
            "recall_per_cost": round((recall / cost_usd), 4) if cost_usd > 0 else 0.0,
        }

    def _best(key: str, *, reverse: bool) -> str | None:
        if not systems:
            return None
        items = sorted(
            systems.items(),
            key=lambda item: item[1].get(key, 0.0),
            reverse=reverse,
        )
        return items[0][0] if items else None

    return {
        "schema": "mimirq.graphrag_bench.v1",
        "summary": {
            "systems_compared": int(len(systems)),
            "best_recall_system": _best("recall", reverse=True),
            "lowest_cost_system": _best("cost_usd", reverse=False),
            "fastest_system": _best("latency_ms", reverse=False),
            "best_cost_efficiency_system": _best("recall_per_cost", reverse=True),
        },
        "systems": systems,
    }


__all__ = ["summarize_graphrag_bench"]
