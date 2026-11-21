import math
from typing import Any


def _to_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        num = float(value)
        if not math.isfinite(num):
            return None
        return num
    except (OverflowError, TypeError, ValueError):
        return None


def summarize_graphrag_bench(rows: list[dict[str, Any]]) -> dict[str, Any]:
    systems: dict[str, dict[str, float | None]] = {}
    for row in rows or []:
        raw_system = (row or {}).get("system")
        if raw_system is None:
            continue
        system = str(raw_system).strip()
        if not system:
            continue
        recall = _to_float((row or {}).get("recall"))
        cost_usd = _to_float((row or {}).get("cost_usd"))
        latency_ms = _to_float((row or {}).get("latency_ms"))
        systems[system] = {
            "recall": round(recall, 4) if recall is not None else None,
            "cost_usd": round(cost_usd, 6) if cost_usd is not None else None,
            "latency_ms": round(latency_ms, 4) if latency_ms is not None else None,
            "recall_per_cost": (round(recall / cost_usd, 4) if cost_usd > 0 else 0.0)
            if recall is not None and cost_usd is not None
            else None,
        }

    def _best(key: str, *, reverse: bool) -> str | None:
        measured = ((name, values[key]) for name, values in systems.items() if values[key] is not None)
        select = max if reverse else min
        best = select(
            measured,
            key=lambda item: item[1],
            default=None,
        )
        return best[0] if best is not None else None

    return {
        "schema": "mimirq.graphrag_bench.v1",
        "summary": {
            "systems_compared": len(systems),
            "best_recall_system": _best("recall", reverse=True),
            "lowest_cost_system": _best("cost_usd", reverse=False),
            "fastest_system": _best("latency_ms", reverse=False),
            "best_cost_efficiency_system": _best("recall_per_cost", reverse=True),
        },
        "systems": systems,
    }


__all__ = ["summarize_graphrag_bench"]
