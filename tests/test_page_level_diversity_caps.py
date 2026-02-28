from __future__ import annotations


def _mk(*, doc_id: str, chunk_index: int, page_number: int | None, score: float) -> dict:
    meta: dict = {"document_id": doc_id, "chunk_index": int(chunk_index)}
    if page_number is not None:
        meta["page_number"] = int(page_number)
    return {
        "chunk_id": f"{doc_id}:{chunk_index}",
        "content": f"chunk {chunk_index}",
        "metadata": meta,
        "score": float(score),
    }


def test_document_diversity_can_cap_chunks_per_page() -> None:
    from app.rag.retriever import HybridRetriever

    r = HybridRetriever()
    r.max_chunks_per_doc = 0
    r.min_distinct_docs = 0
    r.max_chunks_per_page = 1

    results = [
        _mk(doc_id="d1", chunk_index=0, page_number=1, score=0.90),
        _mk(doc_id="d1", chunk_index=1, page_number=1, score=0.89),
        _mk(doc_id="d1", chunk_index=2, page_number=2, score=0.88),
        _mk(doc_id="d1", chunk_index=3, page_number=2, score=0.87),
        _mk(doc_id="d1", chunk_index=4, page_number=3, score=0.86),
    ]

    out = r._apply_document_diversity(results, top_k=3)
    top3 = out[:3]
    assert [int((x.get("metadata") or {}).get("chunk_index")) for x in top3] == [0, 2, 4]

