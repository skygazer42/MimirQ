from __future__ import annotations


def test_convert_image_citations_to_docs_sets_image_metadata() -> None:
    from app.services.chat_image_service import convert_image_citations_to_docs

    citations = [
        {
            "document_id": "d1",
            "document_name": "doc.pdf",
            "chunk_id": "c1",
            "chunk_index": 3,
            "page_number": 2,
            "chunk_content": "Figure 1: Login flow diagram.",
            "relevance_score": 0.91,
            "img_id": "tenant:ds:doc:chunk",
            "img_url": "/api/v1/documents/image-url/tenant:ds:doc:chunk",
            "has_image": True,
        }
    ]

    docs = convert_image_citations_to_docs(citations)
    assert docs and docs[0].metadata
    assert docs[0].metadata.get("retrieval_role") == "image"
    assert docs[0].metadata.get("doc_type_kwd") == "image"
    assert docs[0].metadata.get("img_id") == "tenant:ds:doc:chunk"
    assert "Figure 1" in (docs[0].page_content or "")

