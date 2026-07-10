

def test_chunk_quality_gate_service_returns_structured_reasons() -> None:
    from app.services.chunk_quality_gate import compute_chunk_quality_gate

    gate, _recs, _patches = compute_chunk_quality_gate(
        stats={
            "count": 10,
            "short_count": 7,
            "duplicate_count": 5,
            "covered_chars": 850,
            "coverage_ratio": 0.85,
            "overlap_waste_ratio": 0.70,
            "gap_count": 2,
        },
        total_chunks=10,
        total_characters=1000,
        chunk_size=1000,
        chunk_overlap=200,
        original_text_included=True,
        original_text_truncated=False,
        original_text_max_chars=100000,
    )

    assert gate.get("grade") == "fail"
    reason_items = gate.get("reason_items")
    assert isinstance(reason_items, list) and reason_items

    codes = {r.get("code") for r in reason_items if isinstance(r, dict)}
    assert "coverage_lt_90" in codes
    assert "too_many_short_chunks" in codes
    assert "too_many_duplicates" in codes

