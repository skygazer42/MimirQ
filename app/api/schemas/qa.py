"""
Q&A generation/indexing API schemas.
"""


from uuid import UUID

from pydantic import BaseModel, Field


class QAPairPreview(BaseModel):
    question: str
    answer: str


class DocumentQAGenerateRequest(BaseModel):
    num_pairs: int = Field(default=20, ge=1, le=200, description="Number of Q&A pairs to generate/extract")
    replace_existing: bool = Field(default=True, description="Delete existing QA chunks (file_type=qa) in active version first")
    prefer_llm: bool = Field(default=True, description="Prefer LLM generation when configured; otherwise fall back to extraction")
    max_source_chars: int = Field(default=12_000, ge=500, le=200_000, description="Max chars used as LLM/extraction source")
    preview_pairs: int = Field(default=5, ge=0, le=20, description="Return this many pairs as preview")


class DocumentQAGenerateResponse(BaseModel):
    document_id: UUID
    mode: str = Field(default="none", description="llm | extract | none")
    deleted: int = 0
    created: int = 0
    chunk_ids: list[UUID] = Field(default_factory=list)
    preview: list[QAPairPreview] = Field(default_factory=list)

