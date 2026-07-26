import threading
import time
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

import app.storage.vector.factory as factory_module


class _FakeEmbeddings:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text or ""))] for text in texts]

    def embed_query(self, query: str) -> list[float]:
        return [float(len(query or ""))]


def _doc(content: str) -> dict[str, object]:
    return {"content": content, "metadata": {"chunk_id": uuid4()}}


def _run_in_thread(
    errors: list[BaseException],
    target,
    *args,
) -> threading.Thread:
    def _wrapped() -> None:
        try:
            target(*args)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    return threading.Thread(target=_wrapped)


@pytest.fixture(autouse=True)
def _fake_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        factory_module,
        "create_langchain_embeddings_from_config",
        lambda **_kwargs: _FakeEmbeddings(),
        raising=True,
    )


def test_memory_vector_store_keeps_all_concurrent_updates() -> None:
    store = factory_module.MemoryVectorStore()
    tenant_id = uuid4()
    total_threads = 4
    inserts_per_thread = 25
    start = threading.Event()
    errors: list[BaseException] = []

    def _worker(prefix: str) -> None:
        assert start.wait(timeout=3.0)
        for index in range(inserts_per_thread):
            store.add_documents([_doc(f"{prefix}-{index}")], uuid4(), tenant_id)

    threads = [_run_in_thread(errors, _worker, f"t{idx}") for idx in range(total_threads)]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join(timeout=3.0)
        assert not thread.is_alive()

    assert errors == []
    assert len(store.storage) == total_threads * inserts_per_thread
    assert len({meta["content"] for _vec, meta in store.storage}) == total_threads * inserts_per_thread


def test_faiss_same_tenant_serializes_initialization_and_adds(monkeypatch: pytest.MonkeyPatch) -> None:
    from_texts_started = threading.Event()
    release_first = threading.Event()
    second_add_started = threading.Event()
    from_texts_calls = 0
    add_calls = 0
    lock = threading.Lock()
    errors: list[BaseException] = []

    class _FakeStore:
        def __init__(self, key: str) -> None:
            self.key = key
            self.docstore = SimpleNamespace(_dict={})

        def add_texts(self, **_kwargs) -> None:
            nonlocal add_calls
            with lock:
                add_calls += 1
                second_add_started.set()

        def similarity_search_with_score(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return []

        def save_local(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            return None

    class _FakeFAISS:
        @classmethod
        def from_texts(
            cls,
            *,
            texts: list[str],
            embedding: object,
            metadatas: list[dict[str, object]],
            ids: list[str],
        ) -> _FakeStore:
            del texts, embedding, ids
            nonlocal from_texts_calls
            with lock:
                from_texts_calls += 1
            from_texts_started.set()
            assert release_first.wait(timeout=3.0)
            tenant_key = str(metadatas[0]["tenant_id"])
            return _FakeStore(tenant_key)

    monkeypatch.setattr(factory_module, "_get_faiss_cls", lambda: _FakeFAISS, raising=True)
    monkeypatch.setattr(factory_module.settings, "FAISS_STORE_PATH", "", raising=False)

    store = factory_module.FAISSVectorStore()
    tenant_id = uuid4()

    first = _run_in_thread(errors, store.add_documents, [_doc("first")], uuid4(), tenant_id)
    second = _run_in_thread(errors, store.add_documents, [_doc("second")], uuid4(), tenant_id)

    first.start()
    assert from_texts_started.wait(timeout=3.0)
    second.start()
    time.sleep(0.1)

    assert from_texts_calls == 1
    assert not second_add_started.is_set()

    release_first.set()
    first.join(timeout=3.0)
    second.join(timeout=3.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert from_texts_calls == 1
    assert add_calls == 1


def test_faiss_allows_parallel_adds_across_tenants(monkeypatch: pytest.MonkeyPatch) -> None:
    active_keys: set[str] = set()
    active_guard = threading.Lock()
    overlap_detected = threading.Event()
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    class _FakeStore:
        def __init__(self, key: str) -> None:
            self.key = key
            self.docstore = SimpleNamespace(_dict={})

        def add_texts(self, **_kwargs) -> None:
            with active_guard:
                active_keys.add(self.key)
                if len(active_keys) == 2:
                    overlap_detected.set()
            barrier.wait(timeout=3.0)
            time.sleep(0.05)
            with active_guard:
                active_keys.remove(self.key)

        def similarity_search_with_score(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return []

        def save_local(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            return None

    class _FakeFAISS:
        @classmethod
        def from_texts(
            cls,
            *,
            texts: list[str],
            embedding: object,
            metadatas: list[dict[str, object]],
            ids: list[str],
        ) -> _FakeStore:
            del texts, embedding, ids
            tenant_key = str(metadatas[0]["tenant_id"])
            return _FakeStore(tenant_key)

    monkeypatch.setattr(factory_module, "_get_faiss_cls", lambda: _FakeFAISS, raising=True)
    monkeypatch.setattr(factory_module.settings, "FAISS_STORE_PATH", "", raising=False)

    store = factory_module.FAISSVectorStore()
    tenant_a = uuid4()
    tenant_b = uuid4()
    store.add_documents([_doc("seed-a")], uuid4(), tenant_a)
    store.add_documents([_doc("seed-b")], uuid4(), tenant_b)

    first = _run_in_thread(errors, store.add_documents, [_doc("a")], uuid4(), tenant_a)
    second = _run_in_thread(errors, store.add_documents, [_doc("b")], uuid4(), tenant_b)
    first.start()
    second.start()
    first.join(timeout=3.0)
    second.join(timeout=3.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert overlap_detected.is_set()


def test_chroma_same_collection_serializes_initialization_and_adds(monkeypatch: pytest.MonkeyPatch) -> None:
    init_started = threading.Event()
    release_first = threading.Event()
    second_add_started = threading.Event()
    init_calls = 0
    add_calls = 0
    guard = threading.Lock()
    errors: list[BaseException] = []

    class _FakeChroma:
        def __init__(self, *, collection_name: str, embedding_function: object, persist_directory: str | None = None) -> None:
            del embedding_function, persist_directory
            nonlocal init_calls
            with guard:
                init_calls += 1
            self.collection_name = collection_name
            self._collection = SimpleNamespace(delete=lambda **_kwargs: None, get=lambda **_kwargs: {"ids": [], "metadatas": []})
            self._first_add = True
            init_started.set()
            assert release_first.wait(timeout=3.0)

        def add_texts(self, **_kwargs) -> None:
            nonlocal add_calls
            with guard:
                add_calls += 1
                if not self._first_add:
                    second_add_started.set()
                self._first_add = False

        def similarity_search_with_score(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return []

    monkeypatch.setattr(factory_module, "_get_chroma_cls", lambda: _FakeChroma, raising=True)
    monkeypatch.setattr(factory_module.settings, "CHROMA_PERSIST_PATH", "", raising=False)

    store = factory_module.ChromaVectorStore()
    tenant_id = uuid4()

    first = _run_in_thread(errors, store.add_documents, [_doc("first")], uuid4(), tenant_id)
    second = _run_in_thread(errors, store.add_documents, [_doc("second")], uuid4(), tenant_id)

    first.start()
    assert init_started.wait(timeout=3.0)
    second.start()
    time.sleep(0.1)

    assert init_calls == 1
    assert not second_add_started.is_set()

    release_first.set()
    first.join(timeout=3.0)
    second.join(timeout=3.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert init_calls == 1
    assert add_calls == 2


def test_chroma_add_documents_coerces_nested_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []

    class _FakeChroma:
        def __init__(self, *, collection_name: str, embedding_function: object, persist_directory: str | None = None) -> None:
            del collection_name, embedding_function, persist_directory

        def add_texts(self, texts: list[str], metadatas: list[dict[str, Any]], ids: list[str]) -> None:
            del texts, ids
            captured.extend(metadatas)

        def similarity_search_with_score(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return []

    nested = {
        "chunk_id": uuid4(),
        "element_bbox": {"x0": 1, "x1": 2},
        "labels": [{"name": "header", "page": 1}],
    }

    monkeypatch.setattr(factory_module, "_get_chroma_cls", lambda: _FakeChroma, raising=True)
    store = factory_module.ChromaVectorStore()

    tenant_id = uuid4()
    doc_id = uuid4()
    store.add_documents([{"content": "payload", "metadata": nested}], doc_id, tenant_id)

    assert len(captured) == 1
    meta = captured[0]
    assert isinstance(meta["element_bbox"], str)
    assert isinstance(meta["labels"], str)
    assert "x0" in meta["element_bbox"]
    assert "header" in meta["labels"]
    assert meta["chunk_id"] == str(nested["chunk_id"])
