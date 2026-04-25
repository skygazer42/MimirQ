from __future__ import annotations


def test_compress_plaid_vectors_emits_centroids_and_assignments() -> None:
    from app.rag.retrieval.plaid import compress_plaid_vectors

    out = compress_plaid_vectors(
        token_vectors=[
            [1.0, 0.0],
            [0.9, 0.1],
            [0.0, 1.0],
            [0.1, 0.9],
        ],
        num_centroids=2,
    )

    assert out["schema"] == "mimirq.plaid_compression.v1"
    assert out["original_tokens"] == 4
    assert len(out["centroids"]) == 2
    assert len(out["assignments"]) == 4
    assert sorted(out["cluster_sizes"]) == [2, 2]


def test_compress_plaid_vectors_is_lossless_when_centroids_cover_all_unique_vectors() -> None:
    from app.rag.retrieval.plaid import compress_plaid_vectors, decompress_plaid_vectors

    payload = compress_plaid_vectors(
        token_vectors=[
            [1.0, 0.0],
            [0.0, 1.0],
        ],
        num_centroids=4,
    )
    restored = decompress_plaid_vectors(payload)

    assert restored == [[1.0, 0.0], [0.0, 1.0]]


def test_compress_plaid_vectors_handles_empty_input() -> None:
    from app.rag.retrieval.plaid import compress_plaid_vectors, decompress_plaid_vectors

    payload = compress_plaid_vectors(token_vectors=[], num_centroids=4)
    assert payload["centroids"] == []
    assert payload["assignments"] == []
    assert decompress_plaid_vectors(payload) == []
