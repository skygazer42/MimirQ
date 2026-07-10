
import math
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def percentile(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    if p <= 0:
        return float(sorted_values[0])
    if p >= 100:
        return float(sorted_values[-1])

    n = len(sorted_values)
    pos = (p / 100.0) * (n - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_values[lo])
    frac = pos - lo
    return float(sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac)


def summarize_latencies_ms(latencies_ms: list[float]) -> dict[str, float | int | None]:
    if not latencies_ms:
        return {
            "count": 0,
            "avg": None,
            "min": None,
            "p50": None,
            "p95": None,
            "p99": None,
            "max": None,
        }

    sorted_values = sorted(float(v) for v in latencies_ms)
    count = len(sorted_values)
    avg = sum(sorted_values) / float(count)
    return {
        "count": count,
        "avg": float(avg),
        "min": float(sorted_values[0]),
        "p50": percentile(sorted_values, 50.0),
        "p95": percentile(sorted_values, 95.0),
        "p99": percentile(sorted_values, 99.0),
        "max": float(sorted_values[-1]),
    }


def bounded_top_counts(counter: dict[str, int], *, max_items: int = 10) -> dict[str, int]:
    cap = max(0, int(max_items or 0))
    if cap <= 0:
        return {}
    items = sorted(counter.items(), key=lambda kv: (-int(kv[1]), str(kv[0])))
    out: dict[str, int] = {}
    for k, v in items[:cap]:
        out[str(k)] = int(v)
    return out


def safe_jsonable(value: Any, *, max_str: int = 200) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[: int(max_str or 0)]
    if isinstance(value, list):
        return [safe_jsonable(v, max_str=max_str) for v in value[:50]]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= 50:
                break
            out[str(k)[:80]] = safe_jsonable(v, max_str=max_str)
        return out
    return str(value)[: int(max_str or 0)]


__all__ = [
    "bounded_top_counts",
    "percentile",
    "safe_jsonable",
    "summarize_latencies_ms",
    "utc_now_iso",
]
