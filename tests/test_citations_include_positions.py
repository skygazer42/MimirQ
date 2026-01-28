from __future__ import annotations

from langchain_core.documents import Document

from app.rag.core.citations import build_citations_from_docs


def test_build_citations_includes_position_fields():  # noqa: ANN001
    docs = [
        Document(
            page_content="hello world",
            metadata={
                "document_id": "doc-1",
                "source": "Doc 1",
                "page": 2,
                "chunk_index": 3,
                "start_char": 10,
                "end_char": 20,
                "doc_pipeline_key": "doc-1:abcd",
                "pipeline_hash": "abcd",
            },
        )
    ]
    out = build_citations_from_docs(docs, retrieval_elapsed_sec=0.123, retrieval_mode="vector", query="hello")
    assert len(out) == 1
    c = out[0]
    assert c["page_number"] == 2
    assert c["chunk_index"] == 3
    assert c["start_char"] == 10
    assert c["end_char"] == 20
    assert c["doc_pipeline_key"] == "doc-1:abcd"
    assert c["pipeline_hash"] == "abcd"

