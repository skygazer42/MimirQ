"""Shared output contracts for rule-based and model-based document tagging."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DocumentTagType = Literal["topic", "category", "domain", "industry", "doc_type", "sensitivity", "quality", "keyword"]
SpanAnnotationType = Literal["entity", "keyword", "sensitive", "custom"]

DOCUMENT_TAG_LABELS = {
    "topic": "主题",
    "category": "分类",
    "domain": "领域",
    "industry": "行业",
    "doc_type": "文档类型",
    "sensitivity": "敏感度",
    "quality": "质量线索",
    "keyword": "语义关键词",
}


class DocumentTag(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    type: DocumentTagType
    value: str = Field(min_length=1, max_length=120)
    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = Field(max_length=64)


class SpanAnnotation(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    text: str = Field(min_length=1, max_length=500)
    type: SpanAnnotationType
    label: str = Field(min_length=1, max_length=80)
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = Field(max_length=64)


class TaggingResult(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    summary: str | None = Field(default=None, max_length=1000)
    document_tags: list[DocumentTag] = Field(default_factory=list)
    span_annotations: list[SpanAnnotation] = Field(default_factory=list)
    provider: Literal["cpu", "llm"]


__all__ = [
    "DOCUMENT_TAG_LABELS",
    "DocumentTag",
    "DocumentTagType",
    "SpanAnnotation",
    "SpanAnnotationType",
    "TaggingResult",
]
