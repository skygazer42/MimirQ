import pytest
from fastapi import HTTPException

from app.api.schemas.documents.ingestion import PipelineOptionOverrides, UrlUploadRequest
from app.api.utils import document_pipeline_input as inputs
from app.api.utils.file_io import normalize_upload_key as _normalize_upload_key
from app.api.utils.file_io import sanitize_upload_filename as _sanitize_filename


def test_form_pipeline_overrides_preserve_false_zero_and_unset_values():
    payload = inputs.parse_pipeline_json('{"chunk_size":512,"chunk_overlap":64,"governance_enabled":true}')
    result = inputs.to_pipeline_options(
        pipeline=payload,
        overrides=PipelineOptionOverrides(governance_enabled=False, chunk_overlap=0),
    )
    assert result.chunk_size == 512
    assert result.chunk_overlap == 0
    assert result.governance_enabled is False
    assert inputs.to_pipeline_options().chunk_size is None


def test_invalid_form_override_without_pipeline_is_a_bad_request():
    with pytest.raises(HTTPException) as caught:
        inputs.to_pipeline_options(overrides=PipelineOptionOverrides(chunk_size=0))
    assert caught.value.status_code == 400


@pytest.mark.parametrize("raw", [None, "", "null", "none", "undefined", "   "])
def test_absent_form_pipeline_stays_absent(raw):  # noqa: ANN001
    assert inputs.parse_pipeline_json(raw) is None


@pytest.mark.parametrize("raw", ['{"unexpected":true}', "[]", "not-json"])
def test_invalid_pipeline_keeps_bad_request_contract(raw):  # noqa: ANN001
    with pytest.raises(HTTPException) as caught:
        inputs.parse_pipeline_json(raw)
    assert caught.value.status_code == 400


def test_production_pipeline_error_keeps_implementation_detail_private(monkeypatch):  # noqa: ANN001
    monkeypatch.setattr(inputs, "is_production_env", lambda: True)
    with pytest.raises(HTTPException) as caught:
        inputs.parse_pipeline_json('{"unknown_sensitive_field":"private"}')
    assert caught.value.detail == "Invalid pipeline JSON"


def test_chunk_overlap_rule_is_shared_by_preview_and_ingestion():
    inputs.validate_chunk_params(100, 0)
    with pytest.raises(HTTPException) as caught:
        inputs.validate_chunk_params(100, 100)
    assert caught.value.status_code == 400
    assert caught.value.detail == "chunk_overlap must be less than chunk_size"


def test_shared_upload_name_rules_keep_browser_paths_and_relative_source_keys():
    assert _sanitize_filename(r"C:\fakepath\notes.md") == "notes.md"
    assert _normalize_upload_key(r"folder\nested\notes.md") == "folder/nested/notes.md"
    with pytest.raises(HTTPException) as caught:
        _sanitize_filename("bad\x00name.md")
    assert caught.value.status_code == 400


def test_url_upload_request_remains_a_forbidden_extra_field_contract():
    request = UrlUploadRequest(url="https://example.com/notes.md")
    assert request.dataset_id is None
    assert request.url == "https://example.com/notes.md"
    with pytest.raises(ValueError):
        UrlUploadRequest.model_validate({"url": request.url, "unknown": True})
