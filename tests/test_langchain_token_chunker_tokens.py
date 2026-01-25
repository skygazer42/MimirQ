from __future__ import annotations

from langchain_core.documents import Document

from app.rag.chunking.strategies.token import LangChainTokenChunker


def test_langchain_token_chunker_uses_token_units() -> None:
    chunker = LangChainTokenChunker(chunk_size=10, chunk_overlap=3)
    docs = [Document(page_content=("hello world " * 80).strip(), metadata={})]
    chunks = chunker.split_documents(docs)

    assert chunks, "expected token splitter to produce at least one chunk"
    meta = chunks[0].metadata or {}
    assert meta.get("chunk_size_tokens") == 10
    assert meta.get("chunk_overlap_tokens") == 3

