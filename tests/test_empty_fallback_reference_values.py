import pytest

from app.api.v1.evaluations import _enrich_reference_source_payload


@pytest.mark.parametrize("field", ["quote", "pipeline_hash", "doc_pipeline_key"])
@pytest.mark.parametrize("value", ["", None, False, 0])
def test_reference_enrichment_does_not_replace_a_supplied_value(field, value) -> None:
    source = {field: value}
    result = _enrich_reference_source_payload(
        source,
        chunk_index=0,
        chunk_meta={"pipeline_hash": "current", "doc_pipeline_key": "document:current"},
        chunk_content="stored chunk",
    )
    assert result[field] is value


def test_reference_enrichment_fills_only_missing_fields() -> None:
    result = _enrich_reference_source_payload(
        {},
        chunk_index=0,
        chunk_meta={"pipeline_hash": "current", "doc_pipeline_key": "document:current"},
        chunk_content="stored chunk",
    )
    assert result == {
        "chunk_index": 0,
        "pipeline_hash": "current",
        "doc_pipeline_key": "document:current",
        "quote": "stored chunk",
    }
