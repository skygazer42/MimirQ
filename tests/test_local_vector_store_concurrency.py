import threading
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
