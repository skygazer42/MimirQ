from __future__ import annotations

from math import ceil

_BINS = (
    (0, 500, "0-500"),
    (500, 2000, "500-2000"),
    (2000, 10000, "2000-10000"),
)


def _percentile(values: list[int], pct: int) -> int:
    if not values:
        return 0
    ordered = sorted(int(v) for v in values)
    idx = max(0, min(len(ordered) - 1, ceil((pct / 100.0) * len(ordered)) - 1))
    return int(ordered[idx])


def summarize_length_distribution(lengths: list[int | float]) -> dict:
    values = [max(0, int(v or 0)) for v in (lengths or [])]
    histogram = []
    for start, end, label in _BINS:
        histogram.append(
            {
                "label": label,
                "count": int(sum(1 for v in values if start <= v < end)),
            }
        )
    histogram.append({"label": "10000+", "count": int(sum(1 for v in values if v >= 10000))})

    return {
        "schema": "mimirq.pre_poc.length_distribution.v1",
        "summary": {"count": int(len(values))},
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
