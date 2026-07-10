
from app.rag.retriever import HybridRetriever


def _mk_result(*, doc_id: str, chunk_index: int, score: float, content: str = "") -> dict:
    return {
        "chunk_id": f"{doc_id}:{chunk_index}",
        "content": content or f"chunk {doc_id}:{chunk_index}",
        "metadata": {"document_id": doc_id, "chunk_index": chunk_index, "chunk_id": f"{doc_id}:{chunk_index}"},
        "score": float(score),
    }


def test_budgeted_rrf_fusion_respects_quotas_and_dedup() -> None:
    r = HybridRetriever()

    vector = [
        _mk_result(doc_id="d1", chunk_index=0, score=0.99),
        _mk_result(doc_id="d2", chunk_index=0, score=0.97),
        _mk_result(doc_id="d3", chunk_index=0, score=0.80),
    ]
    bm25 = [
        _mk_result(doc_id="d2", chunk_index=0, score=12.0),
        _mk_result(doc_id="d4", chunk_index=0, score=10.0),
        _mk_result(doc_id="d5", chunk_index=0, score=9.0),
    ]
    lexical = [
        _mk_result(doc_id="d5", chunk_index=0, score=5.0),
        _mk_result(doc_id="d6", chunk_index=0, score=4.0),
    ]
    sparse = [
        _mk_result(doc_id="d7", chunk_index=0, score=3.0),
    ]

    out = r._merge_results(
        vector,
        bm25,
        lexical,
        sparse,
        alpha=0.5,
        fusion_strategy="budgeted_rrf",
        rrf_k=60,
        top_k=4,
    )

    keys = [r._result_key(x) for x in out[:4]]
    # Expected quotas (default): vector=2, bm25=1, lexical=1 (sparse gets 0 for top_k=4)
    # Dedup: d2:0 appears in vector+bm25; bm25 slot should skip it and take d4:0.
    assert set(keys) == {"d1:0", "d2:0", "d4:0", "d5:0"}
    assert len(keys) == 4
    scores = [float(x.get("score") or 0.0) for x in out[:4]]
    assert scores == sorted(scores, reverse=True)

    for item in out[:4]:
        assert item.get("fusion_strategy") == "budgeted_rrf"
        assert 0.0 <= float(item.get("score") or 0.0) <= 1.0
        # Rank-based calibrated scores should be present for observability.
        assert "vector_rank_score" in item
        assert "bm25_rank_score" in item
        assert "lexical_rank_score" in item
        assert "sparse_rank_score" in item


def test_budgeted_rrf_fusion_min_score_threshold_truncates_channel_queue() -> None:
    r = HybridRetriever().model_copy(
        update={
            # Force a quota that would try to take 2 lexical items.
            "fusion_budgets": {"vector": 2, "bm25": 1, "lexical": 2},
            # Only allow the first lexical item (rank_score==1.0).
            "fusion_min_scores": {"lexical": 1.0},
        }
    )

    vector = [
        _mk_result(doc_id="d1", chunk_index=0, score=0.99),
        _mk_result(doc_id="d2", chunk_index=0, score=0.97),
    ]
    bm25 = [
        _mk_result(doc_id="d3", chunk_index=0, score=10.0),
    ]
    lexical = [
        _mk_result(doc_id="d4", chunk_index=0, score=5.0),
        _mk_result(doc_id="d5", chunk_index=0, score=4.0),
    ]
    sparse = [
        _mk_result(doc_id="d6", chunk_index=0, score=3.0),
    ]

    out = r._merge_results(
        vector,
        bm25,
        lexical,
        sparse,
        alpha=0.5,
        fusion_strategy="budgeted_rrf",
        rrf_k=60,
        top_k=5,
    )

    keys = [r._result_key(x) for x in out[:5]]
    # Lexical has quota=2 but threshold keeps only the first lexical item.
    assert set(keys) == {"d1:0", "d2:0", "d3:0", "d4:0", "d6:0"}
    assert "d5:0" not in keys
