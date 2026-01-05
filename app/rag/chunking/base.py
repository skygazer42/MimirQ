"""
Base chunker interface.

All chunking strategies should inherit from BaseChunker.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from langchain_core.documents import Document


class BaseChunker(ABC):
    """Abstract base class for all chunking strategies."""

    @abstractmethod
    def split_documents(self, documents: List[Document]) -> List[Document]:
        """
        Split documents into chunks.

        Args:
            documents: List of LangChain Document objects to split.

        Returns:
            List of chunked Document objects with metadata including:
            - start_char: Start character position in original document
            - end_char: End character position in original document
            - chunk_strategy: Name of the chunking strategy used
        """
        raise NotImplementedError
