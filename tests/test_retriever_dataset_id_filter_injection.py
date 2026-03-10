from __future__ import annotations

import uuid


def test_hybrid_search_injects_dataset_id_into_metadata_filter(monkeypatch):  # noqa: ANN001
    """
    Regression/semantics: dataset-scoped retrieval should push dataset_id into both:
    - vector search metadata_filter (Milvus expr pushdown when supported)
    - BM25 metadata_filter (early filtering to avoid post-trim recall loss)
    """
    import app.rag.retriever as retriever_mod

    dataset_id = uuid.uuid4()

    captured: dict[str, object] = {}

    class _StubVectorStore:
        def search(self, **kwargs):  # noqa: ANN003
            captured["vector_metadata_filter"] = kwargs.get("metadata_filter")
            return []

    monkeypatch.setattr(retriever_mod, "get_vector_store", lambda: _StubVectorStore(), raising=True)

    r = retriever_mod.HybridRetriever(
        tenant_id=uuid.uuid4(),
        account_id="acct",
        dataset_id=dataset_id,
    )

    def _fake_search_bm25(  # noqa: ANN001
        *,
        query: str,
        top_k: int,
        document_ids,
        tenant_id,
        metadata_filter=None,
    ):
        captured["bm25_metadata_filter"] = metadata_filter
        return []

    monkeypatch.setattr(r, "_search_bm25", _fake_search_bm25, raising=True)

    def _fake_search_lexical_db(  # noqa: ANN001
        *,
        query: str,
        top_k: int,
        document_ids,
        tenant_id,
        metadata_filter=None,
    ):
        captured["lexical_metadata_filter"] = metadata_filter
        return []

    # New channel: persistent lexical fallback (Postgres FTS/trigram).
    # Use raising=False for back-compat while the method is being introduced.
    monkeypatch.setattr(r, "_search_lexical_db", _fake_search_lexical_db, raising=False)

    r._hybrid_search(
        query="hello",
        top_k=3,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=r.tenant_id,
        retrieval_mode="hybrid",
        metadata_filter=None,
    )

    want_dataset = str(dataset_id)
    for key in ("vector_metadata_filter", "bm25_metadata_filter", "lexical_metadata_filter"):
        filt = captured.get(key)
        assert isinstance(filt, dict)
        assert filt.get("dataset_id") == want_dataset
