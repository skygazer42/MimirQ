from __future__ import annotations

import uuid


def test_vector_write_batching_adapts_for_large_chunks(monkeypatch):  # noqa: ANN001
    """
    O22 regression test: large docs should reduce vector write batch size
    to avoid spikes (embedding payload + Milvus insert).
    """
    from app.core.config import settings
    from app.storage.vector.milvus import MilvusVectorStore

    monkeypatch.setattr(settings, "VECTOR_WRITE_BATCH_SIZE", 256, raising=True)

    class _DummyStore:
        def __init__(self) -> None:
            self.calls: list[int] = []

        def add_texts(self, *, texts, metadatas, ids):  # noqa: ANN001, ANN201
            _ = metadatas
            self.calls.append(len(texts))
            return list(ids)

    store = _DummyStore()
    vs = MilvusVectorStore()
    vs._store = store  # noqa: SLF001
    vs._ensure_store = lambda: None  # type: ignore[method-assign]

    docs = []
    for _i in range(10):
        docs.append(
            {
                "content": "x" * 50_000,
                "metadata": {"chunk_id": str(uuid.uuid4())},
            }
        )

    out = vs.add_documents(docs, document_id=uuid.uuid4(), tenant_id=uuid.uuid4())
    assert len(out) == len(docs)

    # With adaptive batching, we should not send all 10 chunks in one add_texts() call.
    assert len(store.calls) > 1
    assert max(store.calls) <= 4

