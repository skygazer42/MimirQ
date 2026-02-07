from __future__ import annotations

import uuid


def test_enrich_reference_source_payload_fills_missing_fields():
    from app.api.v1.evaluations import _enrich_reference_source_payload

    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    src = {"document_id": doc_id, "chunk_id": chunk_id}
    out = _enrich_reference_source_payload(
        src,
        chunk_index=7,
        chunk_meta={"doc_pipeline_key": f"{doc_id}:ph", "pipeline_hash": "ph"},
        chunk_content="hello world",
    )

    assert out["document_id"] == doc_id
    assert out["chunk_id"] == chunk_id
    assert out["chunk_index"] == 7
    assert out["doc_pipeline_key"] == f"{doc_id}:ph"
    assert out["pipeline_hash"] == "ph"
    assert out["quote"] == "hello world"


def test_enrich_reference_source_payload_does_not_override_explicit_fields():
    from app.api.v1.evaluations import _enrich_reference_source_payload

    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    src = {
        "document_id": doc_id,
        "chunk_id": chunk_id,
        "chunk_index": 1,
        "doc_pipeline_key": f"{doc_id}:old",
        "pipeline_hash": "old",
        "quote": "explicit quote",
    }
    out = _enrich_reference_source_payload(
        src,
        chunk_index=9,
        chunk_meta={"doc_pipeline_key": f"{doc_id}:new", "pipeline_hash": "new"},
        chunk_content="should not be used",
    )

    assert out["chunk_index"] == 1
    assert out["doc_pipeline_key"] == f"{doc_id}:old"
    assert out["pipeline_hash"] == "old"
    assert out["quote"] == "explicit quote"

