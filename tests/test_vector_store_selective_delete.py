import hashlib
import uuid

import pytest

from app.storage.vector import factory as vector_factory


class _DummyEmbeddings:
    """
    Deterministic, local-only embeddings for unit tests.

    Avoids network calls from the default OpenAI-compatible embedding adapter.
    """

    def __init__(self, dim: int = 8):
        self._dim = int(dim)

    def _vec(self, text: str) -> list[float]:
        raw = (text or "").encode("utf-8")
        digest = hashlib.sha256(raw).digest()
        return [b / 255.0 for b in digest[: self._dim]]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

    def __call__(self, text: str) -> list[float]:
        # LangChain's FAISS wrapper may treat the embedding as a callable embedding_function.
        return self.embed_query(text)


def test_chroma_vector_store_selective_delete_by_metadata_filter(monkeypatch):
    monkeypatch.setattr(
        # Keep unit tests hermetic: persistence is not required for correctness and can be
        # unsupported in some sandbox environments.
        vector_factory.settings,
        "CHROMA_PERSIST_PATH",
        "",
        raising=False,
    )

    store = vector_factory.ChromaVectorStore()
    store.emb = _DummyEmbeddings()

    tenant_id = uuid.uuid4()
    doc1 = uuid.uuid4()
    doc2 = uuid.uuid4()

    store.add_documents(
        [
            {"content": "alpha", "metadata": {"chunk_id": "d1c1"}},
            {"content": "beta", "metadata": {"chunk_id": "d1c2"}},
        ],
        document_id=doc1,
        tenant_id=tenant_id,
    )
    store.add_documents(
        [{"content": "gamma", "metadata": {"chunk_id": "d2c1"}}],
        document_id=doc2,
        tenant_id=tenant_id,
    )

    store.delete_by_document_id_and_filter(
        document_id=doc1,
        tenant_id=tenant_id,
        metadata_filter={"chunk_id": {"$eq": "d1c1"}},
    )

    _, lc_store = store._get_store(tenant_id)
    got = lc_store._collection.get(ids=["d1c1"])  # type: ignore[attr-defined]
    assert got.get("ids") == []
    got = lc_store._collection.get(ids=["d1c2"])  # type: ignore[attr-defined]
    assert got.get("ids") == ["d1c2"]
    got = lc_store._collection.get(ids=["d2c1"])  # type: ignore[attr-defined]
    assert got.get("ids") == ["d2c1"]


def test_faiss_vector_store_selective_delete_by_metadata_filter(monkeypatch):
    try:
        vector_factory._get_faiss_cls()
    except Exception:
        pytest.skip("FAISS optional deps not installed")

    # Avoid persisting/loading from disk in unit tests.
    monkeypatch.setattr(vector_factory.settings, "FAISS_STORE_PATH", "", raising=False)

    store = vector_factory.FAISSVectorStore()
    store.emb = _DummyEmbeddings()

    tenant_id = uuid.uuid4()
    doc1 = uuid.uuid4()
    doc2 = uuid.uuid4()

    store.add_documents(
        [
            {"content": "alpha", "metadata": {"chunk_id": "d1c1"}},
            {"content": "beta", "metadata": {"chunk_id": "d1c2"}},
        ],
        document_id=doc1,
        tenant_id=tenant_id,
    )
    store.add_documents(
        [{"content": "gamma", "metadata": {"chunk_id": "d2c1"}}],
        document_id=doc2,
        tenant_id=tenant_id,
    )

    store.delete_by_document_id_and_filter(
        document_id=doc1,
        tenant_id=tenant_id,
        metadata_filter={"chunk_id": {"$eq": "d1c1"}},
    )

    _, lc_store = store._get_store(tenant_id)
    doc_dict = getattr(lc_store.docstore, "_dict", {})
    assert "d1c1" not in doc_dict
    assert "d1c2" in doc_dict
    assert "d2c1" in doc_dict
