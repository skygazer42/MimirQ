"""Shared chunk coverage, overlap and length/token statistics."""

from collections.abc import Callable, Iterable
from typing import Any, Literal

from app.infrastructure.hashing import stable_hash
from app.infrastructure.tokens import estimate_tokens
from app.services.datasets.profile_statistics import CHUNK_LENGTH_BINS, CHUNK_TOKEN_BINS, HistogramBinSpec, histogram


def _empty_chunk_coverage_metrics(*, largest_gap: int = 0) -> dict[str, float | int]:
    return {
        "sum_chunk_chars": 0,
        "covered_chars": 0,
        "coverage_ratio": 0.0,
        "overlap_waste_ratio": 0.0,
        "gap_count": 0,
        "largest_gap": largest_gap,
    }


def _clip_chunk_ranges(
    ranges: Iterable[tuple[int, int]],
    *,
    total: int,
) -> tuple[int, list[tuple[int, int]]]:
    sum_chunk_chars = 0
    clipped: list[tuple[int, int]] = []
    for start, end in ranges:
        start = max(0, min(total, start))
        end = max(0, min(total, end))
        if end <= start:
            continue
        clipped.append((start, end))
        sum_chunk_chars += end - start
    return sum_chunk_chars, clipped


def _merge_chunk_ranges(
    *,
    clipped: list[tuple[int, int]],
    total: int,
    sum_chunk_chars: int,
) -> dict[str, float | int]:
    clipped.sort(key=lambda item: (item[0], item[1]))
    covered = 0
    gap_count = 0
    largest_gap = 0

    cur_s, cur_e = clipped[0]
    if cur_s > 0:
        gap_count += 1
        largest_gap = max(largest_gap, cur_s)

    for s, e in clipped[1:]:
        if s > cur_e:
            covered += cur_e - cur_s
            gap = s - cur_e
            gap_count += 1
            largest_gap = max(largest_gap, gap)
            cur_s, cur_e = s, e
            continue
        cur_e = max(cur_e, e)

    covered += cur_e - cur_s
    if cur_e < total:
        gap_count += 1
        largest_gap = max(largest_gap, total - cur_e)

    coverage_ratio = covered / total
    overlap_waste_ratio = (sum_chunk_chars - covered) / sum_chunk_chars
    return {
        "sum_chunk_chars": sum_chunk_chars,
        "covered_chars": covered,
        "coverage_ratio": coverage_ratio,
        "overlap_waste_ratio": overlap_waste_ratio,
        "gap_count": gap_count,
        "largest_gap": largest_gap,
    }


def compute_chunk_coverage_metrics_from_ranges(
    ranges: Iterable[tuple[int, int]],
    *,
    total_characters: int,
) -> dict[str, float | int]:
    """
    Compute coverage/overlap signals from chunk start/end ranges.

    Semantics (same as chunk-preview):
    - covered_chars: union length of all chunk ranges (clipped to [0, total_characters])
    - gap_count / largest_gap: uncovered segments within [0, total_characters]
    - overlap_waste_ratio: duplicated chars ratio due to overlap (0-1)
    """
    total = total_characters
    if total <= 0:
        return _empty_chunk_coverage_metrics()

    sum_chunk_chars, clipped = _clip_chunk_ranges(ranges, total=total)

    if not clipped:
        return _empty_chunk_coverage_metrics(largest_gap=total)

    return _merge_chunk_ranges(clipped=clipped, total=total, sum_chunk_chars=sum_chunk_chars)


def _percentile_from_sorted(sorted_values: list[int], p: int) -> int:
    pp = max(0, min(100, p))
    pos = int((pp / 100.0) * (len(sorted_values) - 1))
    return sorted_values[pos]


def compute_chunking_stats_from_lengths(
    lengths: Iterable[int],
    *,
    short_threshold: int = 120,
    duplicate_count: int = 0,
    unit: Literal["chars", "tokens"] = "chars",
    bins: list[HistogramBinSpec] | None = None,
) -> dict[str, Any] | None:
    """
    Compute lightweight chunking stats.

    Notes:
    - `lengths` contains integer chunk sizes, based on stripped content where possible;
      nonpositive values are skipped.
    - `duplicate_count` is best-effort, clamped to zero or higher, and may be 0 when unknown.
    """
    values = [length for length in lengths if length > 0]
    if not values:
        return None

    values.sort()
    total = sum(values)
    short = sum(1 for n in values if n < short_threshold)

    hist = histogram(values, bins or CHUNK_LENGTH_BINS)

    return {
        "unit": unit,
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


def _measure_chunk_texts(
    texts: Iterable[str],
    *,
    measure_length: Callable[[str], int],
) -> tuple[list[int], int]:
    lengths: list[int] = []
    seen: set[str] = set()
    dup_count = 0

    for raw in texts:
        text = raw.strip()
        if not text:
            continue
        lengths.append(measure_length(text))

        digest = stable_hash(text, length=None)
        if digest in seen:
            dup_count += 1
        else:
            seen.add(digest)

    return lengths, dup_count


def compute_chunking_stats_from_texts(
    texts: Iterable[str],
    *,
    short_threshold: int = 120,
    unit: Literal["chars", "tokens"] = "chars",
) -> dict[str, Any] | None:
    """Compute chunking stats from raw chunk texts during ingestion."""
    lengths, duplicate_count = _measure_chunk_texts(texts, measure_length=len)
    return compute_chunking_stats_from_lengths(
        lengths,
        short_threshold=short_threshold,
        duplicate_count=duplicate_count,
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
    lengths, duplicate_count = _measure_chunk_texts(texts, measure_length=estimate_tokens)
    return compute_chunking_stats_from_lengths(
        lengths,
        short_threshold=short_threshold,
        duplicate_count=duplicate_count,
        unit="tokens",
        bins=CHUNK_TOKEN_BINS,
    )


__all__ = [
    "compute_chunk_coverage_metrics_from_ranges",
    "compute_chunking_stats_from_lengths",
    "compute_chunking_stats_from_texts",
    "compute_chunking_stats_from_texts_tokens",
]
