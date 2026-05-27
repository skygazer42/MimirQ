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


def test_build_citations_includes_bbox_from_chunk_metadata():  # noqa: ANN001
    docs = [
        Document(
            page_content="layout citation block",
            metadata={
                "document_id": "doc-1",
                "source": "Layout.pdf",
                "element_page": 4,
                "chunk_index": 8,
                "element_bbox": {"x0": 10, "y0": 20, "x1": 160, "y1": 90},
            },
        )
    ]

    out = build_citations_from_docs(docs, retrieval_elapsed_sec=0.123, retrieval_mode="vector", query="layout")

    assert len(out) == 1
    assert out[0]["bbox"] == {"x0": 10, "y0": 20, "x1": 160, "y1": 90}
    assert out[0]["bbox_page_number"] == 4


def test_build_citations_extracts_bbox_from_deepdoc_position_tags():  # noqa: ANN001
    docs = [
        Document(
            page_content=(
                "Deep Residual Learning for Image Recognition@@1\t152.3\t441.7\t105.7\t119.7##\n"
                "The formulation of F(x) + x can be realized by feedforward neural networks with "
                "shortcut connections@@2\t47.3\t287.7\t363.7\t495.0##"
            ),
            metadata={
                "document_id": "doc-1",
                "source": "deep-residual-learning_1512.03385.pdf",
                "page_index": 1,
                "chunk_index": 0,
            },
        )
    ]

    out = build_citations_from_docs(
        docs,
        retrieval_elapsed_sec=0.123,
        retrieval_mode="vector",
        query="shortcut connections",
    )

    assert len(out) == 1
    assert out[0]["bbox"] == {"x0": 47, "y0": 363, "x1": 287, "y1": 495}
    assert out[0]["bbox_page_number"] == 2


def test_build_citations_includes_policy_fields():  # noqa: ANN001
    docs = [
        Document(
            page_content="第十二条 例外条件如下……",
            metadata={
                "document_id": "doc-1",
                "source": "Policy.pdf",
                "policy_clause_id": "clause-123",
                "policy_clause_number": "第十二条",
                "policy_path": ["第一章 总则", "第十二条"],
                "policy_path_str": "第一章 总则 / 第十二条",
                "parent_id": "parent-12",
            },
        )
    ]
    out = build_citations_from_docs(docs, retrieval_elapsed_sec=0.123, retrieval_mode="vector", query="第十二条")
    assert len(out) == 1
    c = out[0]
    assert c.get("policy_clause_id") == "clause-123"
    assert c.get("policy_clause_number") == "第十二条"
    assert c.get("policy_path_str") == "第一章 总则 / 第十二条"
    assert c.get("parent_id") == "parent-12"


def test_build_citations_includes_hierarchy_family_attribution():  # noqa: ANN001
    docs = [
        Document(
            page_content="child chunk content",
            metadata={
                "document_id": "doc-1",
                "source": "Doc 1",
                "hierarchy_basis": "parent_child",
                "hierarchy_family_key": "family-1",
                "parent_id": "parent-1",
            },
        )
    ]
    out = build_citations_from_docs(docs, retrieval_elapsed_sec=0.123, retrieval_mode="vector", query="child")
    assert len(out) == 1
    c = out[0]
    assert c.get("hierarchy_basis") == "parent_child"
    assert c.get("hierarchy_family_key") == "family-1"
    assert c.get("family_collapse_key") == "family-1"
    assert c.get("family_hit") is True
