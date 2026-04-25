from __future__ import annotations

from collections import Counter
from pathlib import Path


def summarize_format_distribution(paths: list[str]) -> dict:
    counts: Counter[str] = Counter()
    for raw in paths or []:
        path = Path(str(raw or ""))
        suffix = str(path.suffix or "").strip().lower().lstrip(".")
        counts[suffix or "unknown"] += 1

    return {
        "schema": "mimirq.pre_poc.format_distribution.v1",
        "total_files": int(sum(counts.values())),
        "by_extension": dict(sorted(counts.items(), key=lambda kv: kv[0])),
    }


__all__ = ["summarize_format_distribution"]
