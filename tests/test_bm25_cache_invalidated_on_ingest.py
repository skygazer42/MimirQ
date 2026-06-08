from __future__ import annotations

from uuid import uuid4

from langchain_core.documents import Document as LCDocument

from app.rag.retriever import HybridRetriever


class _StubVectorizer:
    def __init__(self, n: int) -> None:
        self._n = int(n)

    def get_scores(self, _processed_query):  # noqa: ANN001
        return [0.1] * self._n


class _StubBM25:
    def __init__(self, n: int) -> None:
        self.preprocess_func = lambda q: q  # noqa: E731
        self.vectorizer = _StubVectorizer(n)


def test_bm25_cache_invalidates_when_dataset_version_changes(monkeypatch) -> None:  # noqa: ANN001
    tenant_id = uuid4()
    dataset_id = uuid4()

    retriever = HybridRetriever()
    retriever.dataset_id = dataset_id

    versions = iter(["v1", "v1", "v2"])
    # O29 introduces this helper; patch with raising=False so this test fails before implementation.
    monkeypatch.setattr(
        HybridRetriever,
        "_bm25_dataset_cache_version",
        lambda _self, *, _tenant_id, _dataset_id: next(versions),
        raising=False,
    )

    build_calls = {"n": 0}

    def _lazy_build_stub(self, *, tenant_id, document_ids, dataset_id=None) -> bool:  # noqa: ANN001
        build_calls["n"] += 1
        tenant_key = self._tenant_key(tenant_id)
        ds = dataset_id or self.dataset_id
        key = f"{tenant_key}:dataset:{ds}"

        docs = [
            LCDocument(
                page_content="x",
                id=str(uuid4()),
                metadata={"document_id": str(uuid4()), "chunk_index": 0},
            )
        ]
        self._bm25_retrievers[key] = _StubBM25(len(docs))
        self._bm25_docs[key] = docs
        return True

    monkeypatch.setattr(HybridRetriever, "_lazy_build_bm25_index", _lazy_build_stub, raising=True)

    # Document IDs omitted => dataset-scoped retrieval. Cache should rebuild when dataset version changes.
    retriever._search_bm25("q", top_k=1, tenant_id=tenant_id)
    retriever._search_bm25("q", top_k=1, tenant_id=tenant_id)
    retriever._search_bm25("q", top_k=1, tenant_id=tenant_id)

    assert int(build_calls["n"]) == 2


def test_bm25_dataset_cache_adopts_initial_version_without_discarding_warm_cache(monkeypatch) -> None:  # noqa: ANN001
    tenant_id = uuid4()
    dataset_id = uuid4()
    cache_doc_id = uuid4()

    retriever = HybridRetriever()
    retriever.dataset_id = dataset_id

    monkeypatch.setattr(
        HybridRetriever,
        "_bm25_dataset_cache_version",
        lambda _self, *, _tenant_id, _dataset_id: "v1",
        raising=False,
    )

    def _lazy_build_stub(self, *, tenant_id, document_ids, dataset_id=None) -> bool:  # noqa: ANN001
        raise AssertionError("warm dataset-scoped BM25 cache should not be discarded")

    monkeypatch.setattr(HybridRetriever, "_lazy_build_bm25_index", _lazy_build_stub, raising=True)

    cache_key = f"{retriever._tenant_key(tenant_id)}:dataset:{dataset_id}"
    docs = [
        LCDocument(
            page_content="warm cache chunk",
            id=str(uuid4()),
            metadata={
                "tenant_id": str(tenant_id),
                "dataset_id": str(dataset_id),
                "document_id": str(cache_doc_id),
                "chunk_index": 0,
            },
        )
    ]
    retriever._bm25_retrievers[cache_key] = _StubBM25(len(docs))
    retriever._bm25_docs[cache_key] = docs

    results = retriever._search_bm25("warm", top_k=1, tenant_id=tenant_id)

    assert results
    assert retriever._bm25_cache_versions[cache_key] == "v1"
    assert retriever._last_bm25_status["reason"] == "ok"
    assert retriever._last_bm25_status["indexed_docs"] == 1
