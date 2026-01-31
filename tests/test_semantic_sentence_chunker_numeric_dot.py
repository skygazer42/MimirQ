from __future__ import annotations

from langchain_core.documents import Document

from app.rag.chunking.strategies.semantic import SemanticSentenceChunker


def test_semantic_sentence_chunker_does_not_split_decimal_number_across_chunks() -> None:
    text = "Pi is 3.14 and more."
    chunker = SemanticSentenceChunker(chunk_size=6, chunk_overlap=0)
    chunks = chunker.split_documents([Document(page_content=text, metadata={})])
    assert chunks
    assert any("3.14" in (c.page_content or "") for c in chunks)

