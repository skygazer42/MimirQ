from math import ceil
from typing import Any

_BINS = (
    (0, 500, "0-500"),
    (500, 2000, "500-2000"),
    (2000, 10000, "2000-10000"),
)


def _percentile(values: list[int], pct: int) -> int:
    if not values:
        return 0
    idx = max(0, min(len(values) - 1, ceil((pct / 100.0) * len(values)) - 1))
    return values[idx]


def summarize_length_distribution(lengths: list[int | float]) -> dict[str, Any]:
    values = sorted(max(0, int(v or 0)) for v in (lengths or []))
    histogram: list[dict[str, str | int]] = []
    for start, end, label in _BINS:
        histogram.append(
            {
                "label": label,
                "count": sum(1 for v in values if start <= v < end),
            }
        )
    histogram.append({"label": "10000+", "count": sum(1 for v in values if v >= 10000)})

    return {
        "schema": "mimirq.pre_poc.length_distribution.v1",
        "summary": {"count": len(values)},
        "percentiles": {
            "p25": _percentile(values, 25),
            "p50": _percentile(values, 50),
            "p75": _percentile(values, 75),
            "p90": _percentile(values, 90),
            "p99": _percentile(values, 99),
        },
        "histogram": histogram,
    }


__all__ = ["summarize_length_distribution"]
