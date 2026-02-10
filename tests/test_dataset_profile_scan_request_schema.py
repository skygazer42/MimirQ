from __future__ import annotations


def test_dataset_profile_scan_request_schema_includes_new_chunk_backfill_flags() -> None:
    from app.api.schemas.dataset_profile import DatasetProfileScanRunCreateRequest

    fields = DatasetProfileScanRunCreateRequest.model_fields

    assert "backfill_chunk_token_stats" in fields
    assert "backfill_chunk_coverage" in fields
    assert "backfill_chunk_quality_gate" in fields

