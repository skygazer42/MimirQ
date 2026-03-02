from __future__ import annotations


def test_build_citations_uses_img_url_when_img_id_missing() -> None:
    from langchain_core.documents import Document

    from app.rag.core.citations import build_citations_from_docs

    docs = [
        Document(
            page_content="image caption text",
            metadata={
                "document_id": "d1",
                "source": "doc.pdf",
                "chunk_id": "c1",
                "retrieval_role": "image",
                "img_url": "/api/v1/documents/image/123",
                "score": 0.9,
            },
            id="c1",
        )
    ]

    citations = build_citations_from_docs(docs, retrieval_elapsed_sec=0.0, retrieval_mode="hybrid", query="image")
    assert citations
    assert citations[0].get("has_image") is True
    assert citations[0].get("img_url") == "/api/v1/documents/image/123"

