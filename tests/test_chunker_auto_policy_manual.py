from __future__ import annotations

from langchain_core.documents import Document

from app.rag.chunking.strategies.auto import AutoChunker


def test_auto_strategy_prefers_policy_manual() -> None:
    text = """第一章 总则
第一条【目的】 ...
第二条 ...
"""
    doc = Document(page_content=text, metadata={"file_type": "txt", "source": "制度.pdf"})
    chunker = AutoChunker(chunk_size=400, chunk_overlap=40)

    _picked, selected = chunker._select(doc)
    assert selected in {"policy_manual_structured", "laws_structured"}
    # Prefer the new one when available.
    assert selected == "policy_manual_structured"

