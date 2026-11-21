"""Document chunks used by reranking."""

from typing import Any

from pydantic import BaseModel, Field


class ChildDocument(BaseModel):
    """Class for storing a piece of text and associated metadata."""

    page_content: str
    vector: list[float] | None = None
    metadata: dict[Any, Any] = Field(default_factory=dict)


class Document(BaseModel):
    """Class for storing a piece of text and associated metadata."""

    page_content: str
    vector: list[float] | None = None
    metadata: dict[Any, Any] = Field(default_factory=dict)
    provider: str | None = None
    children: list[ChildDocument] | None = None
