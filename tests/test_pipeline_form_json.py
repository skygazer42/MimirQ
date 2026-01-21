import pytest
from fastapi import HTTPException

from app.api.schemas.document import DocumentPipelineOptions
from app.api.v1.documents import _parse_pipeline_json, _to_pipeline_options


def test_parse_pipeline_json_empty_is_none():
    assert _parse_pipeline_json(None) is None
    assert _parse_pipeline_json("") is None
    assert _parse_pipeline_json("  ") is None
    assert _parse_pipeline_json("null") is None
    assert _parse_pipeline_json("undefined") is None


def test_parse_pipeline_json_valid():
    raw = (
        '{"governance_enabled": true, "governance_extract_frontmatter": true, '
        '"governance_strip_frontmatter": true, "near_dedup_enabled": true, '
        '"near_dedup_hamming_threshold": 5, "unknown_field": 1}'
    )
    out = _parse_pipeline_json(raw)
    assert isinstance(out, DocumentPipelineOptions)
    assert out.governance_enabled is True
    assert out.governance_extract_frontmatter is True
    assert out.governance_strip_frontmatter is True
    assert out.near_dedup_enabled is True
    assert out.near_dedup_hamming_threshold == 5


def test_parse_pipeline_json_invalid_raises_400():
    with pytest.raises(HTTPException) as exc:
        _parse_pipeline_json("{not valid json")
    assert exc.value.status_code == 400


def test_to_pipeline_options_merge_explicit_form_fields():
    model = _parse_pipeline_json('{"governance_enabled": false, "chunk_size": 1000}')
    opts = _to_pipeline_options(pipeline=model, governance_enabled=True, chunk_size=2000)
    assert opts.governance_enabled is True
    assert opts.chunk_size == 2000

