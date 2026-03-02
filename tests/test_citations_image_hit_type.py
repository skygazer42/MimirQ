from __future__ import annotations


def test_build_citations_sets_image_hit_type_for_image_docs() -> None:
    from langchain_core.documents import Document

    from app.rag.core.citations import build_citations_from_docs

    docs = [
        Document(
            page_content="Diagram caption: OAuth login flow.",
            metadata={
                "document_id": "d1",
                "source": "auth-diagrams.pdf",
                "chunk_id": "c1",
                "chunk_index": 1,
                "retrieval_role": "image",
                "img_id": "tenant:ds:doc:chunk",
                "score": 0.95,
                "vector_score": 0.0,
                "bm25_score": 0.0,
            },
            id="c1",
        )
    ]

    citations = build_citations_from_docs(docs, retrieval_elapsed_sec=0.1, retrieval_mode="hybrid", query="oauth diagram")
    assert citations
    assert citations[0].get("hit_type") == "image"
    assert citations[0].get("has_image") is True

