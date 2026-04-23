from __future__ import annotations

from langchain_core.documents import Document

from app.rag.chunking.strategies.semantic import SemanticSentenceChunker


def test_semantic_sentence_chunker_avoids_tiny_tail_with_default_floor() -> None:
    sentence = "A" * 120 + ". "
    text = sentence * 3

    chunker = SemanticSentenceChunker(chunk_size=300, chunk_overlap=0)
    chunks = chunker.split_documents([Document(page_content=text, metadata={})])

    assert len(chunks) == 1
    assert chunks[0].page_content == text


def test_semantic_sentence_chunker_can_disable_min_chunk_floor() -> None:
    sentence = "A" * 120 + ". "
    text = sentence * 3

    chunker = SemanticSentenceChunker(chunk_size=300, chunk_overlap=0, min_chunk_size=0)
    chunks = chunker.split_documents([Document(page_content=text, metadata={})])

    assert len(chunks) == 2
    assert len(chunks[0].page_content) < len(text)
    assert chunks[0].metadata["chunk_strategy"] == "semantic_sentence"
    assert chunks[1].metadata["chunk_strategy"] == "semantic_sentence"
