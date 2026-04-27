from __future__ import annotations

from uuid import uuid4

from langchain_core.callbacks import CallbackManagerForRetrieverRun


def test_hybrid_search_injects_explicit_entity_key_into_channel_filters(monkeypatch) -> None:  # noqa: ANN001
    import app.rag.retriever as retriever_mod

    captured: dict[str, object] = {}

    class _StubVectorStore:
        def search(self, **kwargs):  # noqa: ANN003
            captured["vector_metadata_filter"] = kwargs.get("metadata_filter")
            return []

    monkeypatch.setattr(retriever_mod, "get_vector_store", lambda: _StubVectorStore(), raising=True)

    r = retriever_mod.HybridRetriever(
        tenant_id=uuid4(),
        account_id="acct",
        entity_key="ACME Holdings",
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

    monkeypatch.setattr(r, "_search_bm25", _fake_search_bm25, raising=True)
    monkeypatch.setattr(r, "_search_lexical_db", _fake_search_lexical_db, raising=False)

    r._hybrid_search(
        query="compare ACME Holdings and ACME",
        top_k=3,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=r.tenant_id,
        retrieval_mode="hybrid",
        metadata_filter=None,
        entity_key="ACME Holdings",
    )

    expected = {"partition_keys": {"$in": ["ACME Holdings"]}}
    assert (captured.get("vector_metadata_filter") or {}).get("partition_keys") == expected["partition_keys"]
    assert captured.get("bm25_metadata_filter") == expected
    assert captured.get("lexical_metadata_filter") == expected


def test_get_relevant_documents_extracts_partition_keys_from_entity_candidates(monkeypatch) -> None:  # noqa: ANN001
    from app.rag.retriever import HybridRetriever

    captured: dict[str, object] = {}

    def _fake_hybrid_search(self, *, query: str, top_k: int, metadata_filter=None, **_kw):  # noqa: ANN001
        captured["query"] = query
        captured["metadata_filter"] = metadata_filter
        return []

    monkeypatch.setattr(HybridRetriever, "_hybrid_search", _fake_hybrid_search, raising=True)

    r = HybridRetriever(
        k=5,
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        account_id="acct",
        entity_candidates=["ACME", "ACME Holdings"],
    )

    _ = r._get_relevant_documents(
        "compare ACME Holdings and ACME",
        run_manager=CallbackManagerForRetrieverRun.get_noop_manager(),
    )

    assert captured.get("metadata_filter") == {"partition_keys": {"$in": ["ACME Holdings", "ACME"]}}
    debug = dict(r._last_debug_metrics or {})
    entity_routing = debug.get("entity_routing") or {}
    assert entity_routing.get("partition_keys") == ["ACME Holdings", "ACME"]
