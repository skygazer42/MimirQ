"""
LangChain TokenTextSplitter wrapper.

Splits text by token count using tiktoken encoding.
"""
from __future__ import annotations

from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import TokenTextSplitter

from app.rag.chunking.base import BaseChunker


class LangChainTokenChunker(BaseChunker):
    """Token-based text splitter using tiktoken encoding."""

    def __init__(
        self,
        chunk_size: int,
        chunk_overlap: int,
        encoding_name: str = "cl100k_base",
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.encoding_name = encoding_name
        self.splitter = TokenTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            encoding_name=encoding_name,
        )

    def split_documents(self, documents: List[Document]) -> List[Document]:
        chunks: List[Document] = []
        for doc in documents:
            text = doc.page_content
            split_texts = self.splitter.split_text(text)
            current_pos = 0
            for split_text in split_texts:
                start_idx = text.find(split_text, current_pos)
                if start_idx == -1:
                    start_idx = current_pos
                end_idx = start_idx + len(split_text)
                metadata = dict(doc.metadata or {})
                metadata["start_char"] = start_idx
                metadata["end_char"] = end_idx
                metadata["chunk_strategy"] = "langchain_token"
                metadata["encoding_name"] = self.encoding_name
                chunks.append(Document(page_content=split_text, metadata=metadata))
                current_pos = max(start_idx + 1, end_idx - len(split_text) // 2)
        return chunks
