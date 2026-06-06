from __future__ import annotations

from langchain_core.documents import Document


def test_build_citations_exposes_plugin_metadata_views_without_private_fields() -> None:
    from app.rag.core.citations import build_citations_from_docs

    docs = [
        Document(
            page_content="步骤说明正文",
            id="c1",
            metadata={
                "document_id": "d1",
                "chunk_id": "c1",
                "source": "一件事操作指引.txt",
                "score": 0.9,
                "section_type": "should-not-leak",
                "_display_metadata": {"case_title": "社会保障卡居民服务“一件事”"},
                "_evaluable_metadata": {
                    "section_type": "operation_steps",
                    "retrieval_intents": ["网上办理怎么操作", "申报步骤"],
                },
                "_indexed_metadata": {"internal_filter": "not-for-citation"},
            },
        )
    ]

    citations = build_citations_from_docs(docs, retrieval_elapsed_sec=0.01, retrieval_mode="hybrid", query="怎么操作")

    assert citations
    metadata = citations[0]["metadata"]
    assert metadata["case_title"] == "社会保障卡居民服务“一件事”"
    assert metadata["section_type"] == "operation_steps"
    assert metadata["retrieval_intents"] == ["网上办理怎么操作", "申报步骤"]
    assert metadata["_evaluable_metadata"]["section_type"] == "operation_steps"
    assert "_indexed_metadata" not in metadata
    assert metadata.get("internal_filter") is None


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


def test_build_citations_includes_kg_path_provenance_when_present() -> None:
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
                "kg_path_provenance": {
                    "schema": "mimirq.kg_path_provenance.v1",
                    "kind": "entity_event_entity",
                    "hops": 2,
                    "nodes": [
                        {"kind": "entity", "entity_id": "e1", "type": "Skill", "name": "SHOULD_DROP"},
                        {"kind": "event", "event_id": "ev1", "document_id": "d1", "chunk_id": "c1"},
                        {"kind": "entity", "entity_id": "e2", "type": "Tool"},
                    ],
                    "edges": [
                        {"kind": "event_entity", "entity_id": "e1", "event_id": "ev1", "document_id": "d1", "chunk_id": "c1"},
                        {"kind": "event_entity", "entity_id": "e2", "event_id": "ev1", "document_id": "d1", "chunk_id": "c1", "evidence_quote": "SHOULD_DROP"},
                    ],
                    "extra": "SHOULD_DROP",
                },
            },
        )
    ]

    citations = build_citations_from_docs(docs, retrieval_elapsed_sec=0.01, retrieval_mode="hybrid", query="q")
    assert citations
    prov = (citations[0] or {}).get("kg_path_provenance")
    assert isinstance(prov, dict)
    assert prov.get("schema") == "mimirq.kg_path_provenance.v1"
    assert prov.get("kind") == "entity_event_entity"
    assert prov.get("hops") == 2
    assert "extra" not in prov
    nodes = prov.get("nodes") or []
    edges = prov.get("edges") or []
    assert isinstance(nodes, list) and len(nodes) == 3
    assert isinstance(edges, list) and len(edges) == 2
    assert "name" not in (nodes[0] or {})
    assert "evidence_quote" not in (edges[1] or {})
