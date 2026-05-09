from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4


def _chunk(
    *,
    chunk_id,
    document_id,
    index: int,
    content: str,
    metadata: dict,
    page: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=chunk_id,
        document_id=document_id,
        chunk_index=index,
        content=content,
        page_number=page,
        start_char=index * 100,
        end_char=index * 100 + len(content),
        doc_metadata=metadata,
    )


def test_build_document_structure_reuses_existing_hierarchy_metadata_without_raw_text() -> None:
    from app.rag.retrieval.document_structure import build_document_structure_from_chunks

    document_id = uuid4()
    doc = SimpleNamespace(
        id=document_id,
        filename="annual-report.pdf",
        file_type="pdf",
        doc_metadata={"page_count": 42, "doc_description": "FY report"},
    )
    risk_chunk_id = uuid4()
    chunks = [
        _chunk(
            chunk_id=uuid4(),
            document_id=document_id,
            index=0,
            page=1,
            content="Executive overview",
            metadata={
                "header_path": ["Executive Summary"],
                "hierarchy_node_key": "exec",
                "hierarchy_family_key": "annual-report:exec",
            },
        ),
        _chunk(
            chunk_id=risk_chunk_id,
            document_id=document_id,
            index=1,
            page=7,
            content="Risk factors include liquidity pressure",
            metadata={
                "header_path": ["Business", "Risk Factors"],
                "hierarchy_node_key": "risk",
                "hierarchy_family_key": "annual-report:risk",
            },
        ),
    ]

    structure = build_document_structure_from_chunks(document=doc, chunks=chunks, max_nodes=20)

    assert structure["schema"] == "mimirq.document_structure.v1"
    assert structure["document"]["document_id"] == str(document_id)
    assert structure["document"]["filename"] == "annual-report.pdf"
    assert structure["document"]["page_count"] == 42
    assert [node["title"] for node in structure["nodes"]] == ["Executive Summary", "Business"]

    business = structure["nodes"][1]
    risk = business["children"][0]
    assert risk["title"] == "Risk Factors"
    assert risk["node_key"] == "risk"
    assert risk["family_key"] == "annual-report:risk"
    assert risk["chunk_ids"] == [str(risk_chunk_id)]
    assert risk["page_start"] == 7
    assert risk["page_end"] == 7
    assert "Risk factors include" not in str(risk)


def test_explain_citations_with_structure_maps_chunks_to_section_path() -> None:
    from app.rag.retrieval.document_structure import (
        build_document_structure_from_chunks,
        explain_citations_with_structure,
    )

    document_id = uuid4()
    chunk_id = uuid4()
    doc = SimpleNamespace(id=document_id, filename="manual.md", file_type="md", doc_metadata={})
    structure = build_document_structure_from_chunks(
        document=doc,
        chunks=[
            _chunk(
                chunk_id=chunk_id,
                document_id=document_id,
                index=0,
                page=None,
                content="Install steps",
                metadata={"outline_path": "Guide / Installation"},
            )
        ],
    )

    trace = explain_citations_with_structure(
        citations=[{"document_id": str(document_id), "chunk_id": str(chunk_id), "source": "manual.md"}],
        structures_by_document={str(document_id): structure},
    )

    assert trace == [
        {
            "citation_index": 0,
            "document_id": str(document_id),
            "chunk_id": str(chunk_id),
            "source": "manual.md",
            "matched": True,
            "node_id": "guide/installation",
            "title": "Installation",
            "path": ["Guide", "Installation"],
            "page_start": None,
            "page_end": None,
            "family_key": None,
        }
    ]
