from __future__ import annotations

import uuid

from langchain_core.documents import Document

from app.rag.core.citations import build_citations_from_docs


def test_hierarchy_parent_citation_inherits_anchor_span_and_snippet() -> None:
    """
    Hierarchy expansion adds parent nodes "for context". Parent chunks often contain
    multiple occurrences of the query terms, so naive snippet extraction can anchor
    to the first occurrence instead of the anchor chunk that triggered expansion.

    Contract: when a hierarchy_parent citation has neighbor_of=<anchor chunk_id>,
    its evidence span should align to the anchor's evidence span when that span lies
    within the parent chunk range.
    """
    document_id = uuid.uuid4()
    anchor_chunk_id = uuid.uuid4()
    parent_chunk_id = uuid.uuid4()

    query = "kWh"
    # Parent contains two matches: one early, one later (the anchor match).
    parent_text = f"Intro {query} appears early.\n" + ("x" * 240) + f" Later {query} appears in the anchor area."
    later_offset = parent_text.find("Later")
    assert later_offset > 0

    anchor_text = parent_text[later_offset : later_offset + 80]
    anchor_start = later_offset

    docs = [
        Document(
            page_content=anchor_text,
            id=str(anchor_chunk_id),
            metadata={
                "retrieval_role": "main",
                "document_id": str(document_id),
                "source": "demo.txt",
                "start_char": anchor_start,
                "end_char": anchor_start + len(anchor_text),
                "score": 1.0,
                "retrieval_score": 1.0,
            },
        ),
        Document(
            page_content=parent_text,
            id=str(parent_chunk_id),
            metadata={
                "retrieval_role": "hierarchy_parent",
                "neighbor_of": str(anchor_chunk_id),
                "document_id": str(document_id),
                "source": "demo.txt",
                "start_char": 0,
                "end_char": len(parent_text),
                "score": 0.5,
                "retrieval_score": 0.5,
            },
        ),
    ]

    citations = build_citations_from_docs(
        docs,
        retrieval_elapsed_sec=0.1,
        retrieval_mode="hybrid",
        query=query,
    )

    by_id = {str(c.get("chunk_id") or ""): c for c in citations}
    anchor_c = by_id[str(anchor_chunk_id)]
    parent_c = by_id[str(parent_chunk_id)]

    assert int(anchor_c.get("evidence_start_char") or 0) > 0
    assert int(anchor_c.get("evidence_end_char") or 0) > int(anchor_c.get("evidence_start_char") or 0)

    # Parent citation should inherit the anchor span (not the first match in parent_text).
    assert parent_c.get("evidence_start_char") == anchor_c.get("evidence_start_char")
    assert parent_c.get("evidence_end_char") == anchor_c.get("evidence_end_char")

    # And the snippet should now be centered around the anchor span (contains "Later ...").
    assert "Later" in str(parent_c.get("chunk_content") or "")

