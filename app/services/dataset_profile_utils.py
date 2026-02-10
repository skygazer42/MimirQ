"""
Dataset profile helpers (aggregation utils).

Keep this module pure and dependency-free so it can be used from:
- API endpoints (real-time summary)
- background jobs (deep scan runs)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence


def safe_int(value: object, *, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        if isinstance(value, bool):
            return int(default)
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return int(default)


def safe_float(value: object, *, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        if isinstance(value, bool):
            return float(default)
        return float(value)  # type: ignore[arg-type]
    except Exception:
        return float(default)


def safe_bool(value: object, *, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def percentile_from_sorted(sorted_values: Sequence[int], p: int) -> int:
    if not sorted_values:
        return 0
    pp = max(0, min(100, int(p)))
    pos = int((pp / 100.0) * (len(sorted_values) - 1))
    pos = max(0, min(len(sorted_values) - 1, pos))
    return int(sorted_values[pos] or 0)


@dataclass(frozen=True)
class HistogramBinSpec:
    label: str
    min: Optional[int] = None
    max: Optional[int] = None

    def contains(self, value: int) -> bool:
        v = int(value or 0)
        if self.min is not None and v < int(self.min):
            return False
        if self.max is not None and v >= int(self.max):
            return False
        return True


def histogram(values: Iterable[int], bins: List[HistogramBinSpec]) -> List[dict]:
    specs = list(bins or [])
    counts = [0 for _ in specs]
    for raw in values:
        v = int(raw or 0)
        for i, spec in enumerate(specs):
            if spec.contains(v):
                counts[i] += 1
                break
    out: List[dict] = []
    for spec, count in zip(specs, counts, strict=False):
        out.append({"label": spec.label, "min": spec.min, "max": spec.max, "count": int(count)})
    return out


# Default bins (v1): tune later based on real customer corpora.
TEXT_LENGTH_BINS: List[HistogramBinSpec] = [
    HistogramBinSpec("0-500", 0, 500),
    HistogramBinSpec("500-2k", 500, 2_000),
    HistogramBinSpec("2k-10k", 2_000, 10_000),
    HistogramBinSpec("10k-50k", 10_000, 50_000),
    HistogramBinSpec("50k+", 50_000, None),
]

FILE_SIZE_BINS: List[HistogramBinSpec] = [
    HistogramBinSpec("0-100KB", 0, 100 * 1024),
    HistogramBinSpec("100KB-1MB", 100 * 1024, 1 * 1024 * 1024),
    HistogramBinSpec("1-5MB", 1 * 1024 * 1024, 5 * 1024 * 1024),
    HistogramBinSpec("5-20MB", 5 * 1024 * 1024, 20 * 1024 * 1024),
    HistogramBinSpec("20MB+", 20 * 1024 * 1024, None),
]

PAGE_COUNT_BINS: List[HistogramBinSpec] = [
    HistogramBinSpec("1-2", 1, 3),
    HistogramBinSpec("3-5", 3, 6),
    HistogramBinSpec("6-10", 6, 11),
    HistogramBinSpec("11-25", 11, 26),
    HistogramBinSpec("26-50", 26, 51),
    HistogramBinSpec("50+", 51, None),
]

# Chunk-level proxies derived from per-document stats:
# - chunk_count: number of chunks per document
# - avg_chunk_chars: approximate avg chunk length = total_characters / chunk_count
CHUNK_COUNT_BINS: List[HistogramBinSpec] = [
    HistogramBinSpec("1-5", 1, 6),
    HistogramBinSpec("6-10", 6, 11),
    HistogramBinSpec("11-20", 11, 21),
    HistogramBinSpec("21-50", 21, 51),
    HistogramBinSpec("51-100", 51, 101),
    HistogramBinSpec("100+", 101, None),
]

AVG_CHUNK_CHARS_BINS: List[HistogramBinSpec] = [
    HistogramBinSpec("0-200", 0, 200),
    HistogramBinSpec("200-500", 200, 500),
    HistogramBinSpec("500-800", 500, 800),
    HistogramBinSpec("800-1.2k", 800, 1_200),
    HistogramBinSpec("1.2k-2k", 1_200, 2_000),
    HistogramBinSpec("2k+", 2_000, None),
]

# Chunk length bins (per-chunk distribution). Keep aligned with AVG_CHUNK_CHARS_BINS for now so
# charts are comparable (doc-level proxy vs real chunk-level).
CHUNK_LENGTH_BINS: List[HistogramBinSpec] = list(AVG_CHUNK_CHARS_BINS)

# Token-length bins for chunk-level stats (used by chunk preview + ingest-time token stats).
# Note: This is intentionally coarse; tune later based on real corpora.
CHUNK_TOKEN_BINS: List[HistogramBinSpec] = [
    HistogramBinSpec("0-50", 0, 50),
    HistogramBinSpec("50-100", 50, 100),
    HistogramBinSpec("100-200", 100, 200),
    HistogramBinSpec("200-400", 200, 400),
    HistogramBinSpec("400-800", 400, 800),
    HistogramBinSpec("800+", 800, None),
]

# Doc-level proxy: average tokens per chunk (derived from ingest-time token stats).
AVG_CHUNK_TOKENS_BINS: List[HistogramBinSpec] = list(CHUNK_TOKEN_BINS)

# Chunk coverage / overlap waste distributions (percentage points).
# These are computed from ingest-time `chunk_coverage.*_ratio` values multiplied by 100.
COVERAGE_PCT_BINS: List[HistogramBinSpec] = [
    HistogramBinSpec("0-50%", 0, 50),
    HistogramBinSpec("50-80%", 50, 80),
    HistogramBinSpec("80-90%", 80, 90),
    HistogramBinSpec("90-98%", 90, 98),
    HistogramBinSpec("98-100%", 98, 101),  # include 100
]

OVERLAP_WASTE_PCT_BINS: List[HistogramBinSpec] = [
    HistogramBinSpec("0-10%", 0, 10),
    HistogramBinSpec("10-20%", 10, 20),
    HistogramBinSpec("20-35%", 20, 35),
    HistogramBinSpec("35-60%", 35, 60),
    HistogramBinSpec("60%+", 60, None),
]
