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


class GeneralStructureChunk(BaseModel):
    """General Structure Chunk."""
    general_chunks: list[str]


class ParentChildChunk(BaseModel):
    """Parent Child Chunk."""
    parent_content: str
    child_contents: list[str]


class ParentChildStructureChunk(BaseModel):
    """Parent Child Structure Chunk."""
    parent_child_chunks: list[ParentChildChunk]
    parent_mode: str = "paragraph"


class QAChunk(BaseModel):
    """QA Chunk."""
    question: str
    answer: str


class QAStructureChunk(BaseModel):
    """QAStructureChunk."""
    qa_chunks: list[QAChunk]


class BaseDocumentTransformer(ABC):
    """Abstract base class for document transformation systems."""

    @abstractmethod
    def transform_documents(self, documents: Sequence[Document], **kwargs: Any) -> Sequence[Document]:
        """Transform a list of documents."""

    @abstractmethod
    async def atransform_documents(self, documents: Sequence[Document], **kwargs: Any) -> Sequence[Document]:
        """Asynchronously transform a list of documents."""


class DocumentContext(BaseModel):
    """Model class for document context."""
    content: str
    score: float | None = None
