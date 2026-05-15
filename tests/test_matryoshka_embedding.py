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


def test_shortlist_then_rescore_uses_low_dim_recall_and_full_dim_ordering() -> None:
    from app.rag.embedding.matryoshka import shortlist_then_rescore

    rows = shortlist_then_rescore(
        query_short_embedding=[1.0, 0.0],
        query_full_embedding=[0.0, 1.0, 0.0],
        corpus_short_embeddings={
            "doc-a": [1.0, 0.0],
            "doc-b": [0.9, 0.1],
            "doc-c": [0.0, 1.0],
        },
        corpus_full_embeddings={
            "doc-a": [0.2, 0.7, 0.0],
            "doc-b": [0.0, 1.0, 0.0],
            "doc-c": [1.0, 0.0, 0.0],
        },
        shortlist_k=2,
        top_k=1,
    )

    assert rows == [
        {
            "document_id": "doc-b",
            "shortlist_rank": 2,
            "shortlist_score": rows[0]["shortlist_score"],
            "rescore_score": 1.0,
        }
    ]
    assert rows[0]["shortlist_score"] > 0.9
