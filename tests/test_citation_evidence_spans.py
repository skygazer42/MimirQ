from __future__ import annotations


def test_build_citations_includes_evidence_span_offsets_when_query_matches():
    from langchain_core.documents import Document

    from app.rag.core.citations import build_citations_from_docs

    prefix = "A" * 300
    suffix = "B" * 300
    text = f"{prefix} beta {suffix}"

    start_char = 1000
    doc = Document(
        page_content=text,
        metadata={
            "document_id": "doc-1",
            "source": "doc-1",
            "chunk_id": "chunk-1",
            "start_char": start_char,
        },
        id="chunk-1",
    )

    citations = build_citations_from_docs(
        [doc],
        retrieval_elapsed_sec=0.01,
        retrieval_mode="vector",
        query="beta",
    )
    assert len(citations) == 1
    c = citations[0]

    assert c.get("evidence_start_char") is not None
    assert c.get("evidence_end_char") is not None
    assert int(c["evidence_start_char"]) >= start_char
    assert int(c["evidence_end_char"]) > int(c["evidence_start_char"])


def test_build_citations_includes_evidence_span_offsets_even_when_no_query_match():
    from langchain_core.documents import Document

    from app.rag.core.citations import build_citations_from_docs

    doc = Document(
        page_content="alpha beta gamma",
        metadata={
            "document_id": "doc-1",
            "source": "doc-1",
            "chunk_id": "chunk-1",
            "start_char": 10,
        },
        id="chunk-1",
    )

    citations = build_citations_from_docs(
        [doc],
        retrieval_elapsed_sec=0.01,
        retrieval_mode="vector",
        query="nope",
    )
    assert len(citations) == 1
    c = citations[0]
    assert c.get("matched_terms") == []
    assert c.get("evidence_start_char") == 10
    assert c.get("evidence_end_char") is not None
    assert int(c["evidence_end_char"]) > int(c["evidence_start_char"])
