from __future__ import annotations


def test_dataset_profile_summary_schema_includes_distribution_fields() -> None:
    from app.api.schemas.dataset_profile import DatasetProfileSummary

    fields = DatasetProfileSummary.model_fields

    assert "page_number_histogram" in fields
    assert "parse_quality_histogram" in fields
    assert "language_mix" in fields

