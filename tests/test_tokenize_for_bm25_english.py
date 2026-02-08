from __future__ import annotations


def test_tokenize_for_bm25_ascii_identifiers_keep_underscore() -> None:
    from app.rag.preprocessing.tokenization import tokenize_for_bm25

    tokens = tokenize_for_bm25("user_id")
    assert "user_id" in tokens
    assert "user" in tokens
    assert "id" in tokens

    tokens = tokenize_for_bm25("USER_ID")
    assert "user_id" in tokens
    assert "user" in tokens
    assert "id" in tokens


def test_tokenize_for_bm25_english_drops_stopwords() -> None:
    from app.rag.preprocessing.tokenization import tokenize_for_bm25

    tokens = tokenize_for_bm25("How to reset password?")
    assert "reset" in tokens
    assert "password" in tokens
    assert "how" not in tokens
    assert "to" not in tokens


def test_tokenize_for_bm25_cjk_still_non_empty() -> None:
    from app.rag.preprocessing.tokenization import tokenize_for_bm25

    tokens = tokenize_for_bm25("如何配置单点登录？")
    assert tokens
