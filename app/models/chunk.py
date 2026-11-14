"""
RAG chunk and document models.

Defines data models and interfaces for document chunks.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field


class ChildDocument(BaseModel):
    """Class for storing a piece of text and associated metadata."""

    page_content: str
    vector: list[float] | None = None
    metadata: dict = Field(default_factory=dict)


class Document(BaseModel):
    """Class for storing a piece of text and associated metadata."""

    page_content: str
    vector: list[float] | None = None
    metadata: dict = Field(default_factory=dict)
    provider: str | None = None
    children: list[ChildDocument] | None = None


class BaseDocumentTransformer(ABC):
    """Abstract base class for document transformation systems."""

    @abstractmethod
    def transform_documents(self, documents: Sequence[Document], **kwargs: Any) -> Sequence[Document]:
        """Transform a list of documents."""

    @abstractmethod
    async def atransform_documents(self, documents: Sequence[Document], **kwargs: Any) -> Sequence[Document]:
        """Asynchronously transform a list of documents."""
