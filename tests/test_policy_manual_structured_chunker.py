from __future__ import annotations

from langchain_core.documents import Document


def test_looks_like_policy_manual_detects_articles() -> None:
    from app.rag.chunking.strategies.policy_manual_structured import looks_like_policy_manual

    text = """第一章 总则
第一条【目的】 本制度用于……
第二条 适用范围……
（一）子款……
"""
    assert looks_like_policy_manual(text) is True


def test_policy_chunker_emits_parent_and_child_with_stable_ids() -> None:
    from app.rag.chunking.strategies.policy_manual_structured import PolicyManualStructuredChunker

    doc = Document(
        page_content="""第一章 总则
第一条【目的】 AAAAA
（一）BBBBB
第二条 CCCCC
""",
        metadata={"document_id": "doc-1", "source": "policy.pdf"},
    )
    chunker = PolicyManualStructuredChunker(chunk_size=200, chunk_overlap=20)
    chunks = chunker.split_documents([doc])

    assert any((c.metadata or {}).get("chunk_role") == "parent" for c in chunks)
    assert any((c.metadata or {}).get("chunk_role") == "child" for c in chunks)

    # Stable ids exist
    for c in chunks:
        meta = c.metadata or {}
        assert meta.get("policy_clause_id")
        assert meta.get("policy_path_str") or meta.get("policy_path")

