from __future__ import annotations

from langchain_core.documents import Document


def test_build_citations_includes_kg_path_when_present() -> None:
    from app.rag.core.citations import build_citations_from_docs

    docs = [
        Document(
            page_content="chunk text",
            id="c1",
            metadata={
                "document_id": "d1",
                "chunk_id": "c1",
                "source": "doc.md",
                "score": 0.9,
                "retrieval_role": "kg",
                "kg_path": [
                    {"entity_id": "e1", "type": "Skill"},
                    {"entity_id": "e2", "type": "Tool"},
                ],
            },
        )
    ]

    citations = build_citations_from_docs(docs, retrieval_elapsed_sec=0.01, retrieval_mode="hybrid", query="q")
    assert citations
    assert (citations[0] or {}).get("kg_path") == [
        {"entity_id": "e1", "type": "Skill"},
        {"entity_id": "e2", "type": "Tool"},
    ]

