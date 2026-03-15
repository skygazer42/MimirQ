from __future__ import annotations

import pytest


def test_compute_chunk_coverage_metrics_from_ranges_overlap_and_gap() -> None:
    from app.services.chunk_coverage_utils import compute_chunk_coverage_metrics_from_ranges

    metrics = compute_chunk_coverage_metrics_from_ranges(
        ranges=[(0, 50), (40, 80)],
        total_characters=100,
    )

    assert metrics["sum_chunk_chars"] == 90
    assert metrics["covered_chars"] == 80
    assert metrics["coverage_ratio"] == pytest.approx(0.8)
    assert metrics["gap_count"] == 1
    assert metrics["largest_gap"] == 20

    # 10 chars overlap out of 90 summed => 11.11...% waste (best-effort float compare)
    assert 0.10 < float(metrics["overlap_waste_ratio"]) < 0.12


def test_compute_chunk_coverage_metrics_from_ranges_multiple_gaps() -> None:
    from app.services.chunk_coverage_utils import compute_chunk_coverage_metrics_from_ranges

    metrics = compute_chunk_coverage_metrics_from_ranges(
        ranges=[(0, 30), (50, 70)],
        total_characters=100,
    )

    assert metrics["sum_chunk_chars"] == 50
    assert metrics["covered_chars"] == 50
    assert metrics["coverage_ratio"] == pytest.approx(0.5)
    assert metrics["overlap_waste_ratio"] == pytest.approx(0.0)
    assert metrics["gap_count"] == 2
    assert metrics["largest_gap"] == 30

