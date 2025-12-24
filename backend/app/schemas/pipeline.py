from __future__ import annotations

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ImageInfo(BaseModel):
    id: str
    url: str
    filename: str


class ParsePreviewResponse(BaseModel):
    backend: str
    pdf_quality: Optional[Dict[str, Any]] = None
    markdown: str
    images: List[ImageInfo] = Field(default_factory=list)


class ChunkItem(BaseModel):
    id: str
    level: str
    index: int
    text: str
    start: int
    end: int
    tokens_est: int
    parent_id: Optional[str] = None


class ChunkPreviewRequest(BaseModel):
    markdown: str


class ChunkPreviewResponse(BaseModel):
    paragraphs: List[ChunkItem]
    sentences: List[ChunkItem]

