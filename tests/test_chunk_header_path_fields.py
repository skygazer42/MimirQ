from __future__ import annotations

from langchain_core.documents import Document

from app.rag.chunking.strategies.markdown import MarkdownAwareChunker
from app.rag.chunking.strategies.outline import OutlineChunker


def test_outline_chunker_emits_header_path_string() -> None:
    text = "1. Intro\nHello\n1.1 Details\nWorld\n"
    chunker = OutlineChunker(chunk_size=200, chunk_overlap=0)
    chunks = chunker.split_documents([Document(page_content=text, metadata={})])
    assert chunks
    assert any(
        isinstance((c.metadata or {}).get("header_path"), str) and (c.metadata or {}).get("header_path")
        for c in chunks
        if isinstance((c.metadata or {}).get("outline_path_str"), str)
    )


def test_markdown_aware_chunker_emits_header_path_string() -> None:
    text = "# Title\nHello world\n"
    chunker = MarkdownAwareChunker(chunk_size=200, chunk_overlap=0)
    chunks = chunker.split_documents([Document(page_content=text, metadata={})])
    assert chunks
    assert any((c.metadata or {}).get("header_path") == "# Title" for c in chunks)

