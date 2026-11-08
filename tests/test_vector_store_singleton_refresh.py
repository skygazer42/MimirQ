import threading
import time
from typing import Any
from uuid import UUID, uuid4


def _dummy_vector_methods(cls: type[Any]) -> type[Any]:
    def add_documents(self, docs: list[dict[str, Any]], document_id: UUID, tenant_id: UUID):  # noqa: ANN001,ARG001
        return []

    def search(  # noqa: ANN001,ARG001
        self,
        query: str,
        top_k: int,
        score_threshold: float,
        document_ids: list[UUID] | None,
        tenant_id: UUID | None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return []

    def delete_by_document_id(self, document_id: UUID, tenant_id: UUID | None = None) -> None:  # noqa: ANN001,ARG001
        return None

    def delete_by_document_id_and_filter(  # noqa: ANN001,ARG001
        self,
        *,
        document_id: UUID,
        tenant_id: UUID | None,
        metadata_filter: dict[str, Any],
    ) -> None:
        return None

    cls.add_documents = add_documents
    cls.search = search
    cls.delete_by_document_id = delete_by_document_id
    cls.delete_by_document_id_and_filter = delete_by_document_id_and_filter
    return cls


def test_get_vector_store_creates_one_memory_singleton_under_race(monkeypatch) -> None:
    import app.storage.vector.factory as factory_module

    factory_module.reset_vector_store_singletons()
    monkeypatch.setattr(factory_module.settings, "VECTOR_BACKEND", "memory", raising=False)

    created: list[object] = []
    created_lock = threading.Lock()
    start = threading.Event()

    @_dummy_vector_methods
    class _SlowStore(factory_module.BaseVectorStore):
        def __init__(self) -> None:
            start.wait(timeout=1.0)
            time.sleep(0.02)
            with created_lock:
                created.append(self)

    monkeypatch.setattr(factory_module, "MemoryVectorStore", _SlowStore, raising=True)

    results: list[object] = []
    result_lock = threading.Lock()

    def _load() -> None:
        start.wait(timeout=1.0)
        store = factory_module.get_vector_store()
        with result_lock:
            results.append(store)

    threads = [threading.Thread(target=_load) for _ in range(4)]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join(timeout=1.0)

    assert len(results) == 4
    assert len({id(store) for store in results}) == 1
    assert len(created) == 1


def test_get_vector_store_embedding_cache_key_changes_without_leaking_api_key(monkeypatch) -> None:
    import app.storage.vector.factory as factory_module

    factory_module.reset_vector_store_singletons()
    monkeypatch.setattr(factory_module.settings, "VECTOR_BACKEND", "memory", raising=False)
    monkeypatch.setattr(factory_module.settings, "EMBEDDING_PROVIDER", "openai_compatible", raising=False)
    monkeypatch.setattr(factory_module.settings, "EMBEDDING_MODEL", "model-a", raising=False)
    monkeypatch.setattr(factory_module.settings, "EMBEDDING_API_BASE", "https://embed-a.example/v1", raising=False)
    monkeypatch.setattr(factory_module.settings, "EMBEDDING_API_KEY", "secret-a", raising=False)

    created: list[object] = []

    @_dummy_vector_methods
    class _Store(factory_module.BaseVectorStore):
        def __init__(self) -> None:
            created.append(self)

    monkeypatch.setattr(factory_module, "MemoryVectorStore", _Store, raising=True)

    first = factory_module.get_vector_store()
    second = factory_module.get_vector_store()

    assert first is second
    assert len(created) == 1
    assert all("secret-a" not in key for key in factory_module._VECTOR_STORE_SINGLETONS)

    monkeypatch.setattr(factory_module.settings, "EMBEDDING_API_KEY", "secret-b", raising=False)
    third = factory_module.get_vector_store()

    assert third is not first
    assert len(created) == 2
    assert all("secret-b" not in key for key in factory_module._VECTOR_STORE_SINGLETONS)


def test_apply_runtime_settings_clears_vector_store_singletons_on_embedding_change(monkeypatch) -> None:
    import app.api.v1.settings as settings_api
    import app.storage.vector.factory as factory_module

    factory_module.reset_vector_store_singletons()
    monkeypatch.setattr(factory_module.settings, "VECTOR_BACKEND", "memory", raising=False)
    monkeypatch.setattr(factory_module.settings, "EMBEDDING_PROVIDER", "openai_compatible", raising=False)
    monkeypatch.setattr(factory_module.settings, "EMBEDDING_MODEL", "model-a", raising=False)
    monkeypatch.setattr(factory_module.settings, "EMBEDDING_API_BASE", "https://embed-a.example/v1", raising=False)
    monkeypatch.setattr(factory_module.settings, "EMBEDDING_API_KEY", "secret-a", raising=False)

    created: list[object] = []

    @_dummy_vector_methods
    class _Store(factory_module.BaseVectorStore):
        def __init__(self) -> None:
            created.append(self)

    monkeypatch.setattr(factory_module, "MemoryVectorStore", _Store, raising=True)

    first = factory_module.get_vector_store()
    assert list(factory_module._VECTOR_STORE_SINGLETONS.values()) == [first]

    settings_api._apply_runtime_settings({"EMBEDDING_MODEL": "model-b"}, ["EMBEDDING_MODEL"])

    assert factory_module._VECTOR_STORE_SINGLETONS == {}

    second = factory_module.get_vector_store()
    assert second is not first
    assert len(created) == 2


def test_factory_get_embedding_client_reuses_active_store_singleton(monkeypatch) -> None:
    import app.storage.vector.factory as factory_module

    factory_module.reset_vector_store_singletons()
    monkeypatch.setattr(factory_module.settings, "VECTOR_BACKEND", "memory", raising=False)

    provider = object()

    @_dummy_vector_methods
    class _Store(factory_module.BaseVectorStore):
        def get_embedding_client(self):  # noqa: ANN201
            return provider

    monkeypatch.setattr(factory_module, "MemoryVectorStore", _Store, raising=True)

    store = factory_module.get_vector_store()
    resolved = factory_module.get_embedding_client()

    assert resolved is provider
    assert store.get_embedding_client() is resolved


def test_factory_get_embedding_client_uses_milvus_public_interface(monkeypatch) -> None:
    import app.storage.vector.factory as factory_module

    sentinel = object()
    monkeypatch.setattr(factory_module.milvus_store, "get_embedding_model", lambda: sentinel, raising=True)

    wrapper = factory_module.MilvusVectorStore()

    assert wrapper.get_embedding_client() is sentinel


class _BlockingEmbeddings:
    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self.started = started
        self.release = release

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if texts and texts[0] == "first":
            self.started.set()
            assert self.release.wait(timeout=1.0)
        return [[1.0] for _ in texts]

    def embed_query(self, _query: str) -> list[float]:
        return [1.0]


def test_memory_vector_store_serializes_concurrent_add_documents(monkeypatch) -> None:
    import app.storage.vector.factory as factory_module

    started = threading.Event()
    release = threading.Event()
    second_done = threading.Event()

    monkeypatch.setattr(
        factory_module,
        "create_langchain_embeddings_from_config",
        lambda **_kwargs: _BlockingEmbeddings(started, release),
        raising=True,
    )

    store = factory_module.MemoryVectorStore()
    tenant_id = uuid4()
    first_doc_id = uuid4()
    second_doc_id = uuid4()

    def _run_first() -> None:
        store.add_documents([{"content": "first", "metadata": {}}], first_doc_id, tenant_id)

    def _run_second() -> None:
        store.add_documents([{"content": "second", "metadata": {}}], second_doc_id, tenant_id)
        second_done.set()

    first_thread = threading.Thread(target=_run_first)
    second_thread = threading.Thread(target=_run_second)

    first_thread.start()
    assert started.wait(timeout=1.0)

    second_thread.start()
    time.sleep(0.05)
    assert not second_done.is_set()

    release.set()
    first_thread.join(timeout=1.0)
    second_thread.join(timeout=1.0)

    assert second_done.is_set()
    assert [meta["document_id"] for _vec, meta in store.storage] == [str(first_doc_id), str(second_doc_id)]
