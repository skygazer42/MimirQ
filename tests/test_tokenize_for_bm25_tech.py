from __future__ import annotations


def test_tokenize_for_bm25_preserves_path_and_segments() -> None:
    from app.rag.preprocessing.tokenization import tokenize_for_bm25

    tokens = tokenize_for_bm25("Call /api/v1/rag/retrieve-preview now")
    assert "api/v1/rag/retrieve-preview" in tokens
    assert "api" in tokens
    assert "v1" in tokens
    assert "rag" in tokens
    assert "retrieve-preview" in tokens
    assert "retrieve" in tokens
    assert "preview" in tokens


def test_tokenize_for_bm25_extracts_semver_subtokens() -> None:
    from app.rag.preprocessing.tokenization import tokenize_for_bm25

    tokens = tokenize_for_bm25("Fixed in v1.2.3")
    assert "v1.2.3" in tokens
    assert "1.2.3" in tokens
    assert "1.2" in tokens


def test_tokenize_for_bm25_splits_camel_case_identifiers() -> None:
    from app.rag.preprocessing.tokenization import tokenize_for_bm25

    tokens = tokenize_for_bm25("Use ChatRAGConfig and BM25Retriever")
    assert "chatragconfig" in tokens
    assert "chat" in tokens
    assert "rag" in tokens
    assert "config" in tokens
    assert "bm25retriever" in tokens
    assert "retriever" in tokens


def test_tokenize_for_bm25_normalizes_numbers_with_commas() -> None:
    from app.rag.preprocessing.tokenization import tokenize_for_bm25

    tokens = tokenize_for_bm25("cost 1,234 USD")
    assert "1234" in tokens

