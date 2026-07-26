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
