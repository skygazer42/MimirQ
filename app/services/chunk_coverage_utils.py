"""
Chunk coverage/overlap metrics utilities.

Used by:
- chunk preview quality signals
- ingestion-time audit metadata
- offline evaluators
"""


from collections.abc import Iterable

from app.rag.core.logging import get_logger


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
    total = int(total_characters or 0)
    rngs = list(ranges or [])
    if total <= 0 or not rngs:
        return {
            "sum_chunk_chars": 0,
            "covered_chars": 0,
            "coverage_ratio": 0.0,
            "overlap_waste_ratio": 0.0,
            "gap_count": 0,
            "largest_gap": 0,
        }

    sum_chunk_chars = 0
    clipped: list[tuple[int, int]] = []
    for s, e in rngs:
        try:
            s0 = int(s)
            e0 = int(e)
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if e0 <= s0:
            continue
        # Clip to document range.
        s2 = max(0, min(total, s0))
        e2 = max(0, min(total, e0))
        if e2 <= s2:
            continue
        clipped.append((s2, e2))
        sum_chunk_chars += max(0, e2 - s2)

    if not clipped:
        return {
            "sum_chunk_chars": 0,
            "covered_chars": 0,
            "coverage_ratio": 0.0,
            "overlap_waste_ratio": 0.0,
            "gap_count": 0,
            "largest_gap": total,
        }

    clipped.sort(key=lambda x: (x[0], x[1]))
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
        else:
            cur_e = max(cur_e, e)

    covered += cur_e - cur_s
    if cur_e < total:
        gap_count += 1
        largest_gap = max(largest_gap, total - cur_e)

    sum_chars = int(sum_chunk_chars)
    covered_chars = int(max(0, covered))
    coverage_ratio = float(covered_chars / total) if total > 0 else 0.0
    overlap_waste_ratio = float(max(0, sum_chars - covered_chars) / sum_chars) if sum_chars > 0 else 0.0

    return {
        "sum_chunk_chars": sum_chars,
        "covered_chars": covered_chars,
        "coverage_ratio": coverage_ratio,
        "overlap_waste_ratio": overlap_waste_ratio,
        "gap_count": int(gap_count),
        "largest_gap": int(largest_gap),
    }


__all__ = ["compute_chunk_coverage_metrics_from_ranges"]

