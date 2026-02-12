from __future__ import annotations


def test_precheck_summary_schema_includes_v3_risk_and_near_dup_fields() -> None:
    from app.api.schemas.dataset_precheck import DatasetPrecheckSummary

    fields = DatasetPrecheckSummary.model_fields
    assert "risk_buckets" in fields
    assert "near_dup_summary" in fields


def test_precheck_ingestion_suggestion_schema_includes_policy_diff_fields() -> None:
    from app.api.schemas.dataset_precheck import DatasetPrecheckIngestionSuggestionResponse

    fields = DatasetPrecheckIngestionSuggestionResponse.model_fields
    assert "before_policy" in fields
    assert "policy_diff" in fields

