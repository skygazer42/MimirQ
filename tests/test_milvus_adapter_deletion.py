import inspect
from types import SimpleNamespace
from uuid import uuid4

import pymilvus
import pytest

from app.storage.vector.milvus import MilvusAdapter, MilvusVectorStore


class _FakeCollection:
    def __init__(self) -> None:
        self.flush_calls = 0

    def flush(self) -> None:
        self.flush_calls += 1


class _LoadedStore:
    def __init__(self) -> None:
        self.col = None
        self.init_calls = 0
        self.delete_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _init(self, **_kwargs) -> None:  # noqa: ANN003
        self.init_calls += 1
        self.col = _FakeCollection()

    def delete(self, *args, **kwargs) -> None:
        self.delete_calls.append((args, kwargs))


@pytest.mark.parametrize(
    "delete_call",
    [
        lambda adapter, tenant_id, document_id: adapter.delete([str(uuid4())]),
        lambda adapter, tenant_id, document_id: adapter.delete_by_document_id(
            document_id,
            tenant_id=tenant_id,
        ),
        lambda adapter, tenant_id, document_id: adapter.delete_by_document_id_and_filter(
            document_id=document_id,
            tenant_id=tenant_id,
            metadata_filter={"chunk_id": {"$eq": str(uuid4())}},
        ),
    ],
)
def test_adapter_delete_is_noop_when_collection_does_not_exist(delete_call) -> None:  # noqa: ANN001
    adapter = MilvusAdapter(collection_name="missing_collection")
    adapter._store = SimpleNamespace(  # noqa: SLF001
        col=None,
        _init=lambda *_args, **_kwargs: None,
        delete=lambda *_args, **_kwargs: pytest.fail("delete must not run without a Milvus collection"),
    )

    delete_call(adapter, uuid4(), uuid4())


@pytest.mark.parametrize(
    "delete_call",
    [
        lambda adapter, tenant_id, document_id: adapter.delete([str(uuid4())]),
        lambda adapter, tenant_id, document_id: adapter.delete_by_document_id(
            document_id,
            tenant_id=tenant_id,
        ),
        lambda adapter, tenant_id, document_id: adapter.delete_by_document_id_and_filter(
            document_id=document_id,
            tenant_id=tenant_id,
            metadata_filter={"chunk_id": {"$eq": str(uuid4())}},
        ),
    ],
)
def test_adapter_delete_loads_collection_before_deleting(monkeypatch: pytest.MonkeyPatch, delete_call) -> None:  # noqa: ANN001
    monkeypatch.setattr(pymilvus, "Collection", _FakeCollection, raising=True)
    adapter = MilvusAdapter(collection_name="missing_collection")
    store = _LoadedStore()
    adapter._store = store  # noqa: SLF001

    delete_call(adapter, uuid4(), uuid4())

    assert store.init_calls == 1
    assert len(store.delete_calls) == 1
    assert store.col.flush_calls == 0


def test_singleton_delete_loads_collection_before_deleting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pymilvus, "Collection", _FakeCollection, raising=True)
    store = MilvusVectorStore()
    fake_store = _LoadedStore()
    store._store = fake_store  # noqa: SLF001

    store.delete_by_document_id(uuid4())

    assert fake_store.init_calls == 1
    assert len(fake_store.delete_calls) == 1
    assert fake_store.col.flush_calls == 0


def test_adapter_lists_semantic_cache_rows_without_requiring_expiry_field() -> None:
    class _Field:
        def __init__(self, name: str) -> None:
            self.name = name

    rows = [{"id": "vec-1", "tenant_id": "tenant-1"}]
    iterator_calls: list[dict[str, object]] = []

    class _Iterator:
        def __init__(self) -> None:
            self.calls = 0
            self.closed = False

        def next(self):  # noqa: ANN202
            self.calls += 1
            if self.calls == 1:
                return list(rows)
            return []

        def close(self) -> None:
            self.closed = True

    class _CollectionWithQuery:
        schema = SimpleNamespace(fields=[_Field("id"), _Field("tenant_id")])

        def query_iterator(self, **kwargs):  # noqa: ANN003,ANN202
            iterator_calls.append(dict(kwargs))
            return _Iterator()

    adapter = MilvusAdapter(collection_name="semantic_cache")
    adapter._store = SimpleNamespace(  # noqa: SLF001
        col=_CollectionWithQuery(),
        _primary_field="id",
    )

    iterator = adapter.open_semantic_cache_maintenance_iterator(tenant_id="tenant-1", batch_size=5)
    listed = iterator.next_batch()
    exhausted = iterator.next_batch() == []
    iterator.close()

    assert listed == [{"id": "vec-1", "tenant_id": "tenant-1", "expires_at_epoch": None, "created_at_epoch": None}]
    assert exhausted is True
    assert iterator_calls == [
        {
            "expr": 'tenant_id == "tenant-1"',
            "batch_size": 5,
            "limit": -1,
            "output_fields": ["id", "tenant_id"],
            "timeout": None,
        }
    ]


def test_adapter_open_semantic_cache_maintenance_iterator_raises_when_tenant_field_missing() -> None:
    class _Field:
        def __init__(self, name: str) -> None:
            self.name = name

    adapter = MilvusAdapter(collection_name="semantic_cache")
    adapter._store = SimpleNamespace(  # noqa: SLF001
        col=SimpleNamespace(schema=SimpleNamespace(fields=[_Field("id")]), query_iterator=lambda **_kwargs: object()),
        _primary_field="id",
    )

    with pytest.raises(RuntimeError, match="tenant_id metadata"):
        adapter.open_semantic_cache_maintenance_iterator(tenant_id="tenant-1", batch_size=5)


def test_adapter_open_semantic_cache_maintenance_iterator_raises_on_query_iterator_failure() -> None:
    class _Field:
        def __init__(self, name: str) -> None:
            self.name = name

    class _CollectionWithQueryFailure:
        schema = SimpleNamespace(fields=[_Field("id"), _Field("tenant_id")])

        def query_iterator(self, **_kwargs):  # noqa: ANN003,ANN202
            raise RuntimeError("boom")

    adapter = MilvusAdapter(collection_name="semantic_cache")
    adapter._store = SimpleNamespace(  # noqa: SLF001
        col=_CollectionWithQueryFailure(),
        _primary_field="id",
    )

    with pytest.raises(RuntimeError, match="query iterator failed"):
        adapter.open_semantic_cache_maintenance_iterator(tenant_id="tenant-1", batch_size=5)


def test_adapter_open_semantic_cache_maintenance_iterator_raises_when_query_iterator_unsupported() -> None:
    class _Field:
        def __init__(self, name: str) -> None:
            self.name = name

    adapter = MilvusAdapter(collection_name="semantic_cache")
    adapter._store = SimpleNamespace(  # noqa: SLF001
        col=SimpleNamespace(schema=SimpleNamespace(fields=[_Field("id"), _Field("tenant_id")])),
        _primary_field="id",
    )

    with pytest.raises(RuntimeError, match="query iterator support"):
        adapter.open_semantic_cache_maintenance_iterator(tenant_id="tenant-1", batch_size=5)


def test_adapter_open_semantic_cache_maintenance_iterator_raises_when_iterator_shape_unsupported() -> None:
    class _Field:
        def __init__(self, name: str) -> None:
            self.name = name

    class _CollectionWithIteratorShapeMismatch:
        schema = SimpleNamespace(fields=[_Field("id"), _Field("tenant_id")])

        def query_iterator(self, **_kwargs):  # noqa: ANN003,ANN202
            return object()

    adapter = MilvusAdapter(collection_name="semantic_cache")
    adapter._store = SimpleNamespace(  # noqa: SLF001
        col=_CollectionWithIteratorShapeMismatch(),
        _primary_field="id",
    )

    with pytest.raises(RuntimeError, match="iterator is unsupported"):
        adapter.open_semantic_cache_maintenance_iterator(tenant_id="tenant-1", batch_size=5)


def test_adapter_semantic_cache_maintenance_uses_query_iterator_not_offset_paging() -> None:
    source = inspect.getsource(MilvusAdapter.open_semantic_cache_maintenance_iterator)

    assert "query_iterator" in source
    assert "offset=" not in source
