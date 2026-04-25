from __future__ import annotations


def test_truncate_embedding_dimension_returns_prefix_slice() -> None:
    from app.rag.embedding.matryoshka import truncate_embedding_dimension

    vec = [float(i) for i in range(8)]
    out = truncate_embedding_dimension(vec, target_dim=4)

    assert out == [0.0, 1.0, 2.0, 3.0]


def test_resolve_matryoshka_dimension_uses_query_complexity_label() -> None:
    from app.rag.embedding.matryoshka import resolve_matryoshka_dimension

    assert resolve_matryoshka_dimension(query_complexity_label="simple", source_dim=1024) == 256
    assert resolve_matryoshka_dimension(query_complexity_label="structured", source_dim=1024) == 512
    assert resolve_matryoshka_dimension(query_complexity_label="multi_hop", source_dim=1024) == 1024


def test_apply_matryoshka_to_embeddings_handles_batches() -> None:
    from app.rag.embedding.matryoshka import apply_matryoshka_to_embeddings

    out = apply_matryoshka_to_embeddings(
        embeddings=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
        target_dim=2,
    )

    assert out == [[0.1, 0.2], [0.4, 0.5]]
