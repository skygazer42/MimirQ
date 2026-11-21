from collections import Counter
from pathlib import Path
from typing import Any


def summarize_format_distribution(paths: list[str]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    for raw in paths or []:
        path = Path(raw)
        suffix = path.suffix.strip().lower().lstrip(".")
        counts[suffix or "unknown"] += 1

    return {
        "schema": "mimirq.pre_poc.format_distribution.v1",
        "total_files": sum(counts.values()),
        "by_extension": dict(sorted(counts.items(), key=lambda kv: kv[0])),
    }


__all__ = ["summarize_format_distribution"]
