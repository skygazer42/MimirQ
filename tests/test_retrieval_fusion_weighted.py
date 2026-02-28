from __future__ import annotations

from app.rag.retriever import HybridRetriever


def _mk_result(*, doc_id: str, chunk_index: int, score: float, content: str = "") -> dict:
    return {
        "chunk_id": f"{doc_id}:{chunk_index}",
        "content": content or f"chunk {doc_id}:{chunk_index}",
        "metadata": {"document_id": doc_id, "chunk_index": chunk_index, "chunk_id": f"{doc_id}:{chunk_index}"},
        "score": float(score),
    }


def test_weighted_fusion_uses_channel_weights_for_ranking() -> None:
    r = HybridRetriever().model_copy(
        update={
            "fusion_weights": {"vector": 0.2, "bm25": 0.8},
        }
    )

    vector = [
        _mk_result(doc_id="d1", chunk_index=0, score=0.99),  # strong vector hit
        _mk_result(doc_id="d2", chunk_index=0, score=0.10),
    ]
    bm25 = [
        _mk_result(doc_id="d2", chunk_index=0, score=12.0),  # strong bm25 hit
        _mk_result(doc_id="d3", chunk_index=0, score=11.0),
    ]

    out = r._merge_results(
        vector,
        bm25,
        [],
        [],
        alpha=0.5,
        fusion_strategy="weighted",
        rrf_k=60,
        top_k=3,
    )

    keys = [r._result_key(x) for x in out[:3]]
    # With bm25 heavily weighted, d2 should outrank d1 even though d1 has the best vector score.
    assert keys[0] == "d2:0"

    for item in out[:3]:
        assert item.get("fusion_strategy") == "weighted"
        assert 0.0 <= float(item.get("score") or 0.0) <= 1.0

