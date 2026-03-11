from __future__ import annotations


def test_dataset_profile_summary_schema_includes_distribution_fields() -> None:
    from app.api.schemas.dataset_profile import DatasetProfileSummary

    fields = DatasetProfileSummary.model_fields

    assert "chunk_count_percentiles" in fields
    assert "chunk_count_histogram" in fields
    assert "avg_chunk_chars_percentiles" in fields
    assert "avg_chunk_chars_histogram" in fields
    assert "chunk_length_percentiles" in fields
    assert "chunk_length_histogram" in fields
    assert "chunk_token_percentiles" in fields
    assert "chunk_token_histogram" in fields
    assert "avg_chunk_tokens_percentiles" in fields
    assert "avg_chunk_tokens_histogram" in fields
    assert "chunk_coverage_percentiles" in fields
    assert "chunk_coverage_histogram" in fields
    assert "chunk_overlap_waste_percentiles" in fields
    assert "chunk_overlap_waste_histogram" in fields
    assert "page_number_histogram" in fields
    assert "parse_quality_histogram" in fields
    assert "language_mix" in fields
    assert "recall_risk_hints" in fields
