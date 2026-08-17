import datetime as dt
from types import SimpleNamespace
from uuid import uuid4

import pymilvus
import pytest

if not hasattr(dt, "UTC"):
    dt.UTC = dt.timezone.utc

from app.storage.vector.milvus import (
    MilvusAdapter,
    MilvusVectorStore,
    _build_milvus_metadata_expr,
)


def test_build_milvus_metadata_expr_translates_supported_clauses_and_indexed_filters() -> None:
    supported = {
        "page_number": {"$gte": 3},
        "source": {"$eq": "report"},
        "__indexed_metadata_filters__": [
            {"field": "region", "condition": {"$in": ["east", "west"]}},
        ],
    }

    expr = _build_milvus_metadata_expr(supported)

    assert expr is not None
    assert 'page_number >= 3' in expr
    assert 'source == "report"' in expr
    assert 'indexed_meta_01_key == "region"' in expr
    assert 'indexed_meta_01_value in ["east", "west"]' in expr


def test_adapter_add_vectors_with_embeddings_batches_upsert_and_strips_reserved_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeCollection:
        def __init__(self) -> None:
            self.upsert_calls: list[tuple[list[list[object]], float | None]] = []
            self.flush_calls = 0

        def upsert(self, insert_list: list[list[object]], timeout: float | None = None, **_kwargs):
            self.upsert_calls.append((insert_list, timeout))
            return SimpleNamespace(primary_keys=[insert_list[0][0]])

        def flush(self) -> None:
            self.flush_calls += 1

    class _FakeStore:
        def __init__(self) -> None:
            self.col = None
            self._primary_field = "id"
            self._text_field = "content"
            self._vector_field = "embedding"
            self.auto_id = False
            self.fields = [
                "id",
                "content",
                "embedding",
                "source",
                "indexed_meta_01_key",
                "indexed_meta_01_value",
            ]
            self.timeout = 7.0
            self.partition_names = ["default"]
            self.replica_number = 2
            self.init_kwargs: list[dict[str, object]] = []

        def _init(self, **kwargs) -> None:
            self.init_kwargs.append(dict(kwargs))
            self.col = _FakeCollection()

    monkeypatch.setattr(pymilvus, "Collection", _FakeCollection, raising=True)

    adapter = MilvusAdapter(collection_name="entities")
    adapter._store = _FakeStore()

    result = adapter.add_vectors(
        [
            {
                "id": "vec-1",
                "content": "alpha",
                "metadata": {
                    "id": "drop-me",
                    "content": "drop-me",
                    "embedding": "drop-me",
                    "source": "doc-a",
                    "_indexed_metadata": {"region": "east"},
                },
            },
            {
                "id": "vec-2",
                "content": "beta",
                "metadata": {
                    "source": "doc-b",
                },
            },
        ],
        embeddings=[[1.0, 2.0], [3.0, 4.0]],
        batch_size=1,
        timeout=11.0,
    )

    store = adapter._store
    collection = store.col

    assert result == ["vec-1", "vec-2"]
    assert len(store.init_kwargs) == 1
    assert store.init_kwargs[0]["partition_names"] == ["default"]
    assert store.init_kwargs[0]["replica_number"] == 2
    assert store.init_kwargs[0]["timeout"] == 7.0
    assert "id" not in store.init_kwargs[0]["metadatas"][0]
    assert "content" not in store.init_kwargs[0]["metadatas"][0]
    assert "embedding" not in store.init_kwargs[0]["metadatas"][0]
    assert store.init_kwargs[0]["metadatas"][0]["indexed_meta_01_key"] == "region"
    assert store.init_kwargs[0]["metadatas"][0]["indexed_meta_01_value"] == "east"
    assert len(collection.upsert_calls) == 2
    assert collection.upsert_calls[0][0][0] == ["vec-1"]
    assert collection.upsert_calls[0][0][1] == ["alpha"]
    assert collection.upsert_calls[0][1] == 7.0
    assert collection.flush_calls == 1


def test_vector_store_add_documents_uses_adaptive_batches_and_maps_metadata_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Store:
        def __init__(self) -> None:
            self.calls: list[tuple[list[str], list[dict[str, object]], list[str]]] = []

        def add_texts(self, *, texts, metadatas, ids):
            self.calls.append((list(texts), [dict(metadata) for metadata in metadatas], list(ids)))
            return list(ids)

    store = object.__new__(MilvusVectorStore)
    store._store = _Store()
    monkeypatch.setattr(store, "_require_store", lambda: store._store, raising=True)
    monkeypatch.setattr(store, "_store_lock", None, raising=False)
    monkeypatch.setattr(store, "_embedding_model", None, raising=False)
    monkeypatch.setattr(store, "_embedding_space_hash", "", raising=False)
    monkeypatch.setattr(store, "_embedding_provider", "local", raising=False)
    monkeypatch.setattr(
        "app.storage.vector.milvus.settings.VECTOR_WRITE_BATCH_SIZE",
        4,
        raising=False,
    )
    monkeypatch.setattr(
        "app.storage.vector.milvus.settings.VECTOR_WRITE_ADAPTIVE_BATCHING_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        "app.storage.vector.milvus.settings.VECTOR_WRITE_BATCH_MAX_CHARS",
        4,
        raising=False,
    )

    document_id = uuid4()
    tenant_id = uuid4()
    result = store.add_documents(
        [
            {
                "content": "aaaa",
                "metadata": {
                    "chunk_id": "chunk-1",
                    "dataset_id": "dataset-1",
                    "page": 7,
                    "img_id": "img-a",
                    "img_url": "https://img/a",
                },
            },
            {
                "content": "bbbb",
                "metadata": {
                    "image_id": "img-b",
                    "image_url": "https://img/b",
                    "pipeline_hash": "pipe-1",
                },
            },
        ],
        document_id=document_id,
        tenant_id=tenant_id,
    )

    calls = store._store.calls

    assert result == ["chunk-1", f"{document_id}_1"]
    assert [call[2] for call in calls] == [["chunk-1"], [f"{document_id}_1"]]
    assert calls[0][1][0]["tenant_id"] == str(tenant_id)
    assert calls[0][1][0]["document_id"] == str(document_id)
    assert calls[0][1][0]["page_number"] == 7
    assert calls[0][1][0]["img_id"] == "img-a"
    assert calls[0][1][0]["image_id"] == "img-a"
    assert calls[0][1][0]["image_url"] == "https://img/a"
    assert calls[1][1][0]["img_id"] == "img-b"
    assert calls[1][1][0]["image_id"] == "img-b"
    assert calls[1][1][0]["image_url"] == "https://img/b"
    assert calls[1][1][0]["doc_pipeline_key"] == f"{document_id}:pipe-1"


def test_vector_store_fetch_existing_ids_dedupes_and_batches_queries() -> None:
    class _Collection:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def query(self, **kwargs):
            self.calls.append(dict(kwargs))
            return [{"id": "vec-1"}, {"id": "vec-3"}]

    store = object.__new__(MilvusVectorStore)
    collection = _Collection()
    store._store = SimpleNamespace(col=collection, _primary_field="id")
    store._require_store = lambda: store._store

    result = store.fetch_existing_ids(
        ["vec-1", "vec-1", "vec-2", "vec-3"],
        max_ids_per_query=2,
        timeout=5.0,
    )

    assert result == {"vec-1", "vec-3"}
    assert len(collection.calls) == 2
    assert collection.calls[0]["output_fields"] == ["id"]
    assert collection.calls[0]["timeout"] == 5.0
    assert 'id in ["vec-1", "vec-2"]' == collection.calls[0]["expr"]
    assert 'id in ["vec-3"]' == collection.calls[1]["expr"]


def test_vector_store_fetch_vectors_by_ids_coerces_supported_vector_shapes() -> None:
    class _VectorWithList:
        def tolist(self) -> list[float]:
            return [5.0, 6.0]

    class _Collection:
        def query(self, **kwargs):
            assert kwargs["output_fields"] == ["id", "embedding"]
            return [
                {"id": "vec-1", "embedding": [1, 2.5]},
                {"id": "vec-2", "embedding": (3, 4)},
                {"id": "vec-3", "embedding": _VectorWithList()},
                {"id": "vec-4", "embedding": ["bad"]},
            ]

    store = object.__new__(MilvusVectorStore)
    store._store = SimpleNamespace(col=_Collection(), _primary_field="id", _vector_field="embedding")
    store._require_store = lambda: store._store

    result = store.fetch_vectors_by_ids(["vec-1", "vec-2", "vec-3", "vec-4"])

    assert result == {
        "vec-1": [1.0, 2.5],
        "vec-2": [3.0, 4.0],
        "vec-3": [5.0, 6.0],
    }


def test_vector_store_fetch_vectors_by_ids_returns_empty_on_query_failure() -> None:
    class _Collection:
        def query(self, **_kwargs):
            raise RuntimeError("boom")

    store = object.__new__(MilvusVectorStore)
    store._store = SimpleNamespace(col=_Collection(), _primary_field="id", _vector_field="embedding")
    store._require_store = lambda: store._store

    assert store.fetch_vectors_by_ids(["vec-1"]) == {}
