from __future__ import annotations


def test_precheck_summary_schema_includes_extreme_fields() -> None:
    from app.api.schemas.dataset_precheck import DatasetPrecheckSummary

    fields = DatasetPrecheckSummary.model_fields
    assert "schema_id" in fields
    assert "schema_version" in fields
    assert "by_file_type_bytes" in fields
    assert "file_type_stats" in fields
    assert "language_mix" in fields
    assert "directory_stats" in fields
    assert "primary_tag_counts" in fields
    assert "processing_path_counts" in fields


def test_precheck_file_schema_includes_language_fields() -> None:
    from app.api.schemas.dataset_precheck import DatasetPrecheckFileOut

    fields = DatasetPrecheckFileOut.model_fields
    assert "language" in fields
    assert "language_confidence" in fields
    assert "primary_tag" in fields
    assert "processing_paths" in fields
    assert "parse_failure_kind" in fields
