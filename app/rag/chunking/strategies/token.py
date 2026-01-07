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
        # Pipeline-level chunk_size/chunk_overlap are defined in "characters"
        # across strategies; TokenTextSplitter expects token counts. We use a
        # simple chars->tokens heuristic (≈ chars/4) to keep semantics aligned.
        self.chunk_size_chars = int(chunk_size)
        self.chunk_overlap_chars = int(chunk_overlap)
        self.chunk_size_tokens = max(1, int(self.chunk_size_chars // 4) or 1)
        self.chunk_overlap_tokens = max(0, int(self.chunk_overlap_chars // 4) or 0)
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            self.chunk_overlap_tokens = max(0, self.chunk_size_tokens - 1)

        self.encoding_name = encoding_name
        self.splitter = TokenTextSplitter(
            chunk_size=self.chunk_size_tokens,
            chunk_overlap=self.chunk_overlap_tokens,
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
                metadata["chunk_size_chars"] = self.chunk_size_chars
                metadata["chunk_overlap_chars"] = self.chunk_overlap_chars
                metadata["chunk_size_tokens"] = self.chunk_size_tokens
                metadata["chunk_overlap_tokens"] = self.chunk_overlap_tokens
                chunks.append(Document(page_content=split_text, metadata=metadata))
                current_pos = max(start_idx + 1, end_idx - len(split_text) // 2)
        return chunks
