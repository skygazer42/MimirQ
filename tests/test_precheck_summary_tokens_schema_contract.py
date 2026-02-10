from __future__ import annotations


def test_precheck_summary_schema_includes_token_distribution_fields() -> None:
    from app.api.schemas.dataset_precheck import DatasetPrecheckSummary

    fields = DatasetPrecheckSummary.model_fields
    assert "token_percentiles" in fields
    assert "token_histogram" in fields

