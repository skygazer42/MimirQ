import hashlib
from uuid import UUID

from app.services.indexer import _ensure_chunk_metadata


def test_ensure_chunk_metadata_fills_defaults():
    doc_id = UUID(int=1)
    meta = {}
    out = _ensure_chunk_metadata(meta, content=" hello ", document_id=doc_id, chunk_index=2)

    assert out["chunk_key"] == f"{doc_id}:2"
    assert out["content_len"] == 5
    assert out["content_hash_algo"] == "sha256"
    assert out["content_hash"] == hashlib.sha256("hello".encode("utf-8", "ignore")).hexdigest()


def test_ensure_chunk_metadata_does_not_override_existing_values():
    doc_id = UUID(int=1)
    meta = {"chunk_key": "custom", "content_hash": "abc", "content_len": 123}
    out = _ensure_chunk_metadata(meta, content="hello", document_id=doc_id, chunk_index=0)

    assert out["chunk_key"] == "custom"
    assert out["content_hash"] == "abc"
    assert out["content_len"] == 123
    assert "content_hash_algo" not in out

