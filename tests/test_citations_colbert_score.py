from __future__ import annotations

from langchain_core.documents import Document

from app.rag.core.citations import build_citations_from_docs


def test_build_citations_includes_colbert_score_and_hit_type():  # noqa: ANN001
    docs = [
        Document(
            page_content="alpha beta",
            metadata={
                "document_id": "doc-1",
                "source": "Doc 1",
                # ColBERT ANN candidate-generation scaffold emits `colbert_score` in metadata.
                "colbert_score": 0.42,
            },
            id="chunk-1",
        )
    ]

    out = build_citations_from_docs(docs, retrieval_elapsed_sec=0.123, retrieval_mode="vector", query="alpha")
    assert len(out) == 1
    c = out[0]
    assert c.get("colbert_score") == 0.42
    assert c.get("hit_type") == "colbert_ann"

