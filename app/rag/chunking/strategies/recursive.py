"""
LangChain RecursiveCharacterTextSplitter wrapper.

Preserves start/end character positions for highlighting.
"""
from __future__ import annotations

from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


class LangChainRecursiveChunker(BaseChunker):
    """RecursiveCharacterTextSplitter wrapper with position tracking."""

    # Default separators optimized for Chinese and English
    DEFAULT_SEPARATORS = ["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]

    def __init__(
        self,
        chunk_size: int,
        chunk_overlap: int,
        separators: List[str] = None,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or self.DEFAULT_SEPARATORS
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=self.separators,
            length_function=len,
        )

    def split_documents(self, documents: List[Document]) -> List[Document]:
        chunks: List[Document] = []
        for doc in documents:
            docs = self.splitter.create_documents(
                texts=[doc.page_content],
                metadatas=[dict(doc.metadata or {})]
            )
            offset = 0
            for chunk in docs:
                start_index = chunk.metadata.pop("start_index", None)
                metadata = dict(doc.metadata or {})
                metadata.update(chunk.metadata or {})
                if start_index is not None:
                    metadata["start_char"] = start_index
                    metadata["end_char"] = start_index + len(chunk.page_content)
                metadata["chunk_strategy"] = "langchain_recursive"
                chunks.append(Document(page_content=chunk.page_content, metadata=metadata))
                offset += len(chunk.page_content)
        return chunks
