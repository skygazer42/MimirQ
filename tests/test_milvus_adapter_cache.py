from app.storage.vector.milvus import get_milvus_adapter


def test_get_milvus_adapter_caches_instances():
    a1 = get_milvus_adapter("test_collection", vector_field="embedding", text_field="content")
    a2 = get_milvus_adapter("test_collection", vector_field="embedding", text_field="content")
    b1 = get_milvus_adapter("test_collection", vector_field="vec", text_field="content")

    assert a1 is a2
    assert a1 is not b1


def test_milvus_adapter_flushes_direct_embedding_writes(monkeypatch):
    """
    KG writes pass precomputed embeddings into MilvusAdapter.add_vectors().
    That direct path must flush after upsert/insert so Milvus collection counts
    and follow-up vector recall observe the newly written KG vectors.
    """

    import sys
    from types import SimpleNamespace

    from app.storage.vector.milvus import MilvusAdapter

    class _Result:
        primary_keys = ["vec-1"]

    class _FakeCollection:
        def __init__(self):
            self.upsert_calls = 0
            self.flush_calls = 0

        def upsert(self, insert_list, timeout=None, **kwargs):  # noqa: ANN001
            self.upsert_calls += 1
            return _Result()

        def flush(self):
            self.flush_calls += 1

    fake_collection = _FakeCollection()

    class _FakeStore:
        _text_field = "content"
        _vector_field = "embedding"
        _primary_field = "id"
        _metadata_field = None
        auto_id = False
        fields = ["content", "embedding", "id", "tenant_id"]
        timeout = None
        col = fake_collection

    monkeypatch.setitem(
        sys.modules,
        "pymilvus",
        SimpleNamespace(Collection=_FakeCollection, MilvusException=Exception),
    )

    adapter = MilvusAdapter("kg_events")
    adapter._store = _FakeStore()  # type: ignore[attr-defined]

    out = adapter.add_vectors(
        [{"id": "vec-1", "content": "event content", "metadata": {"tenant_id": "tenant-1"}}],
        embeddings=[[0.1, 0.2]],
    )

    assert out == ["vec-1"]
    assert fake_collection.upsert_calls == 1
    assert fake_collection.flush_calls == 1
