from __future__ import annotations


def test_embed_code_snippet_returns_deterministic_vector() -> None:
    from app.rag.embedding.code_embedder import embed_code_snippet

    a = embed_code_snippet("def hello():\n    return 1", dimension=8)
    b = embed_code_snippet("def hello():\n    return 1", dimension=8)

    assert a == b
    assert len(a) == 8


def test_embed_code_snippet_changes_when_source_changes() -> None:
    from app.rag.embedding.code_embedder import embed_code_snippet

    a = embed_code_snippet("def hello():\n    return 1", dimension=8)
    b = embed_code_snippet("def hello(name):\n    return name", dimension=8)

    assert a != b
