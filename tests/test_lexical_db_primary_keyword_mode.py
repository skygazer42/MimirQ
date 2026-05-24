from __future__ import annotations

from uuid import uuid4

from app.core.config import settings
from app.rag.retriever import HybridRetriever


def _lexical_hit(document_id: str, *, score: float = 0.9) -> dict[str, object]:
    return {
        "document_id": document_id,
        "chunk_id": f"{document_id}:0",
        "content": f"lexical:{document_id}",
        "score": score,
        "metadata": {
            "document_id": document_id,
            "chunk_id": f"{document_id}:0",
            "chunk_index": 0,
            "lexical_method": "fts",
        },
        "lexical_score": score,
    }


def _bm25_hit(document_id: str, *, score: float = 7.5) -> dict[str, object]:
    return {
        "document_id": document_id,
        "chunk_id": f"{document_id}:0",
        "content": f"bm25:{document_id}",
        "score": score,
        "metadata": {
            "document_id": document_id,
            "chunk_id": f"{document_id}:0",
            "chunk_index": 0,
        },
        "bm25_score": score,
    }


def test_keyword_mode_prefers_lexical_db_and_skips_bm25_by_default(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_KEYWORD_BM25_SECONDARY_ENABLED", False, raising=False)

    retriever = HybridRetriever(tenant_id=uuid4(), account_id="acct")
    calls: list[str] = []

    monkeypatch.setattr(
        retriever,
        "_search_lexical_db",
        lambda **_kwargs: calls.append("lexical") or [_lexical_hit("doc-lexical")],
        raising=True,
    )
    monkeypatch.setattr(
        retriever,
        "_search_bm25",
        lambda **_kwargs: calls.append("bm25") or [_bm25_hit("doc-bm25")],
        raising=True,
    )

    results = retriever._hybrid_search(
        query="release notes",
        top_k=2,
        score_threshold=0.0,
        tenant_id=retriever.tenant_id,
        retrieval_mode="keyword",
    )

    assert calls == ["lexical"]
    assert len(results) == 1
    assert results[0]["document_id"] == "doc-lexical"

    channels = retriever._last_channel_metrics
    assert channels["keyword_strategy"]["primary"] == "lexical_db"
    assert channels["keyword_strategy"]["bm25_secondary_enabled"] is False
    assert channels["keyword_strategy"]["lexical_db_used"] is True
    assert channels["keyword_strategy"]["bm25_used"] is False
    assert channels["lexical_db"]["candidates"] == 1
    assert channels["bm25"]["candidates"] == 0


def test_keyword_mode_can_run_bm25_as_secondary_after_lexical(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_KEYWORD_BM25_SECONDARY_ENABLED", True, raising=False)

    retriever = HybridRetriever(tenant_id=uuid4(), account_id="acct")
    calls: list[str] = []

    monkeypatch.setattr(
        retriever,
        "_search_lexical_db",
        lambda **_kwargs: calls.append("lexical") or [_lexical_hit("doc-lexical")],
        raising=True,
    )
    monkeypatch.setattr(
        retriever,
        "_search_bm25",
        lambda **_kwargs: calls.append("bm25") or [_bm25_hit("doc-bm25")],
        raising=True,
    )

    results = retriever._hybrid_search(
        query="release notes",
        top_k=4,
        score_threshold=0.0,
        tenant_id=retriever.tenant_id,
        retrieval_mode="keyword",
    )

    assert calls == ["lexical", "bm25"]
    assert {item["document_id"] for item in results} == {"doc-lexical", "doc-bm25"}

    channels = retriever._last_channel_metrics
    assert channels["keyword_strategy"]["primary"] == "lexical_db"
    assert channels["keyword_strategy"]["secondary"] == "bm25"
    assert channels["keyword_strategy"]["bm25_secondary_enabled"] is True
    assert channels["keyword_strategy"]["lexical_db_used"] is True
    assert channels["keyword_strategy"]["bm25_used"] is True
    assert channels["counts"]["lexical_candidates"] == 1
    assert channels["counts"]["bm25_candidates"] == 1


def test_keyword_mode_falls_back_to_bm25_when_lexical_primary_returns_empty(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_KEYWORD_BM25_SECONDARY_ENABLED", False, raising=False)

    retriever = HybridRetriever(tenant_id=uuid4(), account_id="acct")
    calls: list[str] = []

    class _StubVectorStore:
        def search(self, **_kwargs):  # noqa: ANN003
            calls.append("vector")
            return [_bm25_hit("doc-vector")]

    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: _StubVectorStore(), raising=True)
    monkeypatch.setattr(
        retriever,
        "_search_lexical_db",
        lambda **_kwargs: calls.append("lexical") or [],
        raising=True,
    )
    monkeypatch.setattr(
        retriever,
        "_search_bm25",
        lambda **_kwargs: calls.append("bm25") or [_bm25_hit("doc-bm25")],
        raising=True,
    )

    results = retriever._hybrid_search(
        query="apac review",
        top_k=2,
        score_threshold=0.0,
        tenant_id=retriever.tenant_id,
        retrieval_mode="keyword",
    )

    assert calls == ["lexical", "bm25"]
    assert len(results) == 1
    assert results[0]["document_id"] == "doc-bm25"

    channels = retriever._last_channel_metrics
    assert channels["keyword_strategy"]["primary"] == "lexical_db"
    assert channels["keyword_strategy"]["bm25_secondary_enabled"] is False
    assert channels["keyword_strategy"]["lexical_db_used"] is False
    assert channels["keyword_strategy"]["bm25_used"] is True
    assert channels["counts"]["lexical_candidates"] == 0
    assert channels["counts"]["bm25_candidates"] == 1
    assert channels["counts"]["vector_candidates"] == 0


def test_hybrid_mode_skips_lexical_db_when_primary_channels_are_sufficient(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_HYBRID_FALLBACK_ONLY", True, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)

    retriever = HybridRetriever(tenant_id=uuid4(), account_id="acct")
    calls: list[str] = []

    class _StubVectorStore:
        def search(self, **_kwargs):  # noqa: ANN003
            calls.append("vector")
            return [_bm25_hit("doc-vector-1"), _bm25_hit("doc-vector-2")]

    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: _StubVectorStore(), raising=True)
    monkeypatch.setattr(
        retriever,
        "_search_bm25",
        lambda **_kwargs: calls.append("bm25") or [_bm25_hit("doc-bm25-1"), _bm25_hit("doc-bm25-2")],
        raising=True,
    )
    monkeypatch.setattr(
        retriever,
        "_search_lexical_db",
        lambda **_kwargs: calls.append("lexical") or [_lexical_hit("doc-lexical")],
        raising=True,
    )

    results = retriever._hybrid_search(
        query="release notes",
        top_k=3,
        score_threshold=0.0,
        tenant_id=retriever.tenant_id,
        retrieval_mode="hybrid",
    )

    assert calls == ["vector", "bm25"]
    assert len(results) == 3

    channels = retriever._last_channel_metrics
    assert channels["lexical_db"]["enabled"] is True
    assert channels["lexical_db"]["used"] is False
    assert channels["lexical_db"]["run_reason"] == "skipped_primary_candidates_sufficient"
    assert channels["timing"]["lexical_ms"] == 0.0


def test_hybrid_mode_uses_lexical_db_when_primary_channels_are_insufficient(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_HYBRID_FALLBACK_ONLY", True, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)

    retriever = HybridRetriever(tenant_id=uuid4(), account_id="acct")
    calls: list[str] = []

    class _StubVectorStore:
        def search(self, **_kwargs):  # noqa: ANN003
            calls.append("vector")
            return []

    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: _StubVectorStore(), raising=True)
    monkeypatch.setattr(
        retriever,
        "_search_bm25",
        lambda **_kwargs: calls.append("bm25") or [],
        raising=True,
    )
    monkeypatch.setattr(
        retriever,
        "_search_lexical_db",
        lambda **_kwargs: calls.append("lexical") or [_lexical_hit("doc-lexical")],
        raising=True,
    )

    results = retriever._hybrid_search(
        query="release notes",
        top_k=3,
        score_threshold=0.0,
        tenant_id=retriever.tenant_id,
        retrieval_mode="hybrid",
    )

    assert calls == ["vector", "bm25", "lexical"]
    assert len(results) == 1

    channels = retriever._last_channel_metrics
    assert channels["lexical_db"]["used"] is True
    assert channels["lexical_db"]["run_reason"] == "hybrid_fallback"
    assert channels["counts"]["lexical_candidates"] == 1
