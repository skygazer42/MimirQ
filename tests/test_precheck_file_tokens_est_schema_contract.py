from __future__ import annotations


def test_precheck_file_schema_includes_text_tokens_est() -> None:
    from app.api.schemas.dataset_precheck import DatasetPrecheckFileOut

    fields = DatasetPrecheckFileOut.model_fields
    assert "text_tokens_est" in fields

