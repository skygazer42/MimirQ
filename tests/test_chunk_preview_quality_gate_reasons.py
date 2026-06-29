from __future__ import annotations


def test_chunk_preview_quality_gate_has_structured_reason_items():
    from app.api.schemas.document import ChunkPreviewStats
    from app.services.document_preview_utils import _compute_chunk_preview_quality

    stats = ChunkPreviewStats(
        unit="chars",
        count=10,
        short_count=7,
        duplicate_count=5,
        covered_chars=850,
        coverage_ratio=0.85,
        overlap_waste_ratio=0.70,
        gap_count=2,
    )

    gate, _recs, _patches = _compute_chunk_preview_quality(
        stats=stats,
        total_chunks=10,
        total_characters=1000,
        chunk_size=1000,
        chunk_overlap=200,
        original_text_included=True,
        original_text_truncated=False,
        original_text_max_chars=100000,
    )

    assert gate.grade == "fail"
    reason_items = getattr(gate, "reason_items", None)
    assert isinstance(reason_items, list) and reason_items, "quality_gate.reason_items must be a non-empty list"

    codes = {getattr(r, "code", None) for r in reason_items}
    assert "coverage_lt_90" in codes
    assert "too_many_short_chunks" in codes
    assert "too_many_duplicates" in codes
