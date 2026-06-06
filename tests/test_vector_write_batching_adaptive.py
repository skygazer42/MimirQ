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


def test_milvus_add_documents_flattens_indexed_metadata_slots(monkeypatch):  # noqa: ANN001
    from app.core.config import settings
    from app.storage.vector.milvus import MilvusVectorStore, _rehydrate_indexed_metadata_slots

    monkeypatch.setattr(settings, "VECTOR_WRITE_BATCH_SIZE", 256, raising=True)

    class _DummyStore:
        def __init__(self) -> None:
            self.metadatas: list[dict] = []

        def add_texts(self, *, texts, metadatas, ids):  # noqa: ANN001, ANN201
            _ = texts
            self.metadatas.extend(dict(meta) for meta in metadatas)
            return list(ids)

    store = _DummyStore()
    vs = MilvusVectorStore()
    vs._store = store  # noqa: SLF001
    vs._ensure_store = lambda: None  # type: ignore[method-assign]

    document_id = uuid.uuid4()
    out = vs.add_documents(
        [
            {
                "content": "Demo record content",
                "metadata": {
                    "chunk_id": str(uuid.uuid4()),
                    "_indexed_metadata": {
                        "business_type": "demo_service",
                        "district": "north-region",
                    },
                },
            }
        ],
        document_id=document_id,
        tenant_id=uuid.uuid4(),
    )

    assert len(out) == 1
    assert len(store.metadatas) == 1
    metadata = store.metadatas[0]
    assert metadata["indexed_meta_01_key"] == "business_type"
    assert metadata["indexed_meta_01_value"] == "demo_service"
    assert metadata["indexed_meta_02_key"] == "district"
    assert metadata["indexed_meta_02_value"] == "north-region"
    assert _rehydrate_indexed_metadata_slots(metadata)["_indexed_metadata"] == {
        "business_type": "demo_service",
        "district": "north-region",
    }


def test_milvus_search_rehydrates_indexed_metadata_slots_for_client_filter() -> None:
    from app.storage.vector.milvus import MilvusVectorStore, _flatten_indexed_metadata_slots

    class _Doc:
        id = "chunk-1"
        page_content = "Demo record content"

        def __init__(self) -> None:
            self.metadata = {
                "tenant_id": "tenant-a",
                "dataset_id": "dataset-a",
                "document_id": "doc-a",
                "chunk_id": "chunk-1",
                **_flatten_indexed_metadata_slots(
                    {"_indexed_metadata": {"business_type": "demo_service"}}
                ),
            }

    class _DummyStore:
        def __init__(self) -> None:
            self.expr: str | None = None

        def similarity_search_with_score(self, query, *, k, expr):  # noqa: ANN001, ANN201
            _ = query, k
            self.expr = expr
            return [(_Doc(), 0.9)]

    store = _DummyStore()
    vs = MilvusVectorStore()
    vs._store = store  # noqa: SLF001
    vs._ensure_store = lambda: None  # type: ignore[method-assign]

    results = vs.search(
        "account renewal",
        top_k=1,
        score_threshold=0.1,
        metadata_filter={"business_type": "demo_service"},
    )

    assert store.expr is not None
    assert 'indexed_meta_01_key == "business_type"' in store.expr
    assert results[0]["metadata"]["_indexed_metadata"] == {"business_type": "demo_service"}
