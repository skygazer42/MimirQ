from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID


def test_indexer_indexes_kg_event_vectors_with_pipeline_hash_metadata() -> None:
    """
    KG event vectors should include pipeline scoping metadata so downstream vector filters
    (and diagnostics) can avoid mixing document versions.
    """
    from app.services.indexer import Indexer

    captured: dict[str, object] = {}

    class _FakeVector:
        def add_vectors(self, items, embeddings=None):  # noqa: ANN001
            captured["items"] = items
            captured["embeddings"] = embeddings
            return [str(i.get("id")) for i in items]

    idx = Indexer.__new__(Indexer)
    idx._event_vector = _FakeVector()  # type: ignore[attr-defined]

    ev = SimpleNamespace(
        id=UUID(int=1),
        tenant_id=UUID(int=2),
        document_id=UUID(int=3),
        chunk_id=UUID(int=4),
        title="Event",
        summary="Summary",
        content="Content",
        content_vector=[0.1, 0.2],
        references={"chunk_index": 0},
        pipeline_hash="ph-v1",
    )

    out = idx._index_event_vectors([ev])
    assert out == [str(UUID(int=1))]

    items = captured.get("items") or []
    assert isinstance(items, list) and len(items) == 1
    meta = (items[0] or {}).get("metadata") or {}
    assert meta.get("pipeline_hash") == "ph-v1"
    assert meta.get("doc_pipeline_key") == f"{UUID(int=3)}:ph-v1"

