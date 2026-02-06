from __future__ import annotations

from langchain_core.documents import Document


def test_fuse_docs_rrf_prefers_higher_hit_count_on_ties() -> None:
    """
    When multiple docs tie on fused score, prefer docs that appear in more queries.

    This improves stability/quality for query-expansion fusion (multi-query/decompose/HyDE).
    """
    from app.rag.engine import RAGEngine

    doc_a = Document(page_content="a", metadata={"document_id": "doc-a", "chunk_index": 1, "score": 0.99})
    doc_b = Document(page_content="b", metadata={"document_id": "doc-b", "chunk_index": 1, "score": 0.10})

    # Second query: put doc_b at rank=5 so its RRF contribution ties with doc_a's rank=1
    # when rrf_k=1: 1/(1+2) + 1/(1+5) == 1/(1+1)
    dummy1 = Document(page_content="d1", metadata={"document_id": "dummy-1", "chunk_index": 1, "score": 0.0})
    dummy2 = Document(page_content="d2", metadata={"document_id": "dummy-2", "chunk_index": 1, "score": 0.0})
    dummy3 = Document(page_content="d3", metadata={"document_id": "dummy-3", "chunk_index": 1, "score": 0.0})
    dummy4 = Document(page_content="d4", metadata={"document_id": "dummy-4", "chunk_index": 1, "score": 0.0})

    out = RAGEngine.fuse_docs_rrf(
        [[doc_a, doc_b], [dummy1, dummy2, dummy3, dummy4, doc_b]],
        rrf_k=1,
        meta_prefix="qe",
    )

    assert out, "expected fused docs"
    assert (out[0].metadata or {}).get("document_id") == "doc-b"
    assert (out[0].metadata or {}).get("qe_hits") == 2
    assert (out[0].metadata or {}).get("qe_fused") is True
