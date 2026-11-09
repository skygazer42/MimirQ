"""
Chunking stats helpers (shared by ingest + deep scan + manual chunk ingestion).

This module is intentionally dependency-light so it can be used from:
- parsing/ingest pipeline (DocumentProcessorService)
- dataset profile deep scan backfills
- manual chunk ingestion endpoints
"""

import hashlib
from collections.abc import Iterable
from typing import Any

from app.core.token_utils import estimate_tokens
from app.rag.core.logging import get_logger
from app.services.dataset_profile_utils import CHUNK_LENGTH_BINS, CHUNK_TOKEN_BINS, HistogramBinSpec, histogram


def _percentile_from_sorted(sorted_values: list[int], p: int) -> int:
    if not sorted_values:
        return 0
    pp = max(0, min(100, p))
    pos = int((pp / 100.0) * (len(sorted_values) - 1))
    pos = max(0, min(len(sorted_values) - 1, pos))
    return sorted_values[pos]


def compute_chunking_stats_from_lengths(
    lengths: Iterable[int],
    *,
    short_threshold: int = 120,
    duplicate_count: int = 0,
    unit: str = "chars",
    bins: list[HistogramBinSpec] | None = None,
) -> dict[str, Any] | None:
    """
    Compute lightweight chunking stats.

    Notes:
    - `lengths` should already be based on stripped content where possible; values that
      cannot be converted to integers or are nonpositive are skipped.
    - `duplicate_count` is best-effort, clamped to zero or higher, and may be 0 when unknown.
    """
    values: list[int] = []
    for raw in lengths:
        try:
            n = int(raw)
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if n <= 0:
            continue
        values.append(n)

    if not values:
        return None

    values.sort()
    total = sum(values)
    short = sum(1 for n in values if n < short_threshold)

    hist = histogram(values, bins or CHUNK_LENGTH_BINS)

    return {
        "unit": unit or "chars",
        "count": len(values),
        "total": total,
        "min": values[0],
        "max": values[-1],
        "avg": round(total / len(values)),
        "median": _percentile_from_sorted(values, 50),
        "p10": _percentile_from_sorted(values, 10),
        "p90": _percentile_from_sorted(values, 90),
        "short_threshold": short_threshold,
        "short_count": short,
        "duplicate_count": max(0, duplicate_count),
        "histogram": hist,
    }


def compute_chunking_stats_from_texts(
    texts: Iterable[str],
    *,
    short_threshold: int = 120,
    unit: str = "chars",
) -> dict[str, Any] | None:
    """
    Compute chunking stats from raw chunk texts (best-effort).

    This is suitable when we have chunk strings in memory (ingest / manual upload).
    """
    lengths: list[int] = []
    seen: set[str] = set()
    dup_count = 0

    for raw in texts:
        text = raw.strip()
        if not text:
            continue
        lengths.append(len(text))

        digest = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()
        if digest in seen:
            dup_count += 1
        else:
            seen.add(digest)

    return compute_chunking_stats_from_lengths(
        lengths,
        short_threshold=short_threshold,
        duplicate_count=dup_count,
        unit=unit,
    )


def compute_chunking_stats_from_texts_tokens(
    texts: Iterable[str],
    *,
    short_threshold: int = 40,
) -> dict[str, Any] | None:
    """
    Compute token-based chunking stats from raw chunk texts (best-effort).

    Notes:
    - Uses `estimate_tokens` (fast heuristic) to avoid heavy tokenization costs during ingestion.
    - Keeps duplicate detection identical to char-based stats (content sha256).
    """
    lengths: list[int] = []
    seen: set[str] = set()
    dup_count = 0

    for raw in texts:
        text = raw.strip()
        if not text:
            continue
        lengths.append(estimate_tokens(text))

        digest = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()
        if digest in seen:
            dup_count += 1
        else:
            seen.add(digest)

    return compute_chunking_stats_from_lengths(
        lengths,
        short_threshold=short_threshold,
        duplicate_count=dup_count,
        unit="tokens",
        bins=CHUNK_TOKEN_BINS,
    )
