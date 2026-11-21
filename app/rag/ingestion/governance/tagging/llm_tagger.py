"""Typed model responses and owned client scope for document auto tagging."""

from contextlib import AsyncExitStack
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.rag.ingestion.governance.tagging import (
    DOCUMENT_TAG_LABELS,
    DocumentTag,
    DocumentTagType,
    SpanAnnotation,
    SpanAnnotationType,
    TaggingResult,
)
from app.rag.llm.base import BaseLLMClient
from app.rag.llm.factory import create_llm_client
from app.rag.llm.models import LLMMessage, LLMRole
from app.rag.llm.prompts.tagger_prompts import AUTO_TAGGER_RESPONSE_SCHEMA, AUTO_TAGGER_SYSTEM_PROMPT

_OMITTED_CONTENT_MARKER = "\n\n[... omitted middle content ...]\n\n"


_DEFAULT_CONFIDENCE = 0.85


class _TaggerSpan(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    type: SpanAnnotationType = "custom"
    label: str | None = Field(default=None, max_length=80)
    confidence: float = Field(default=_DEFAULT_CONFIDENCE, ge=0.0, le=1.0)


class _TaggerResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    summary: str | None = Field(default=None, max_length=1000)
    topics: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    keywords_semantic: list[str] = Field(default_factory=list)
    quality_signals: list[str] = Field(default_factory=list)
    domain: str | None = None
    industry: str | None = None
    doc_type: str | None = None
    sensitivity: str | None = None
    annotations: list[_TaggerSpan] = Field(default_factory=list)

    @field_validator("topics", "categories", "keywords_semantic", "quality_signals", "annotations", mode="before")
    @classmethod
    def _empty_collections(cls, value: object) -> object:
        # The existing model prompt explicitly allows null for an absent field.
        return [] if value is None else value


def build_tagger_context(text: str, *, max_chars: int = 3000) -> str:
    clean = text.strip()
    limit = max(0, max_chars)
    if len(clean) <= limit:
        return clean
    if limit <= len(_OMITTED_CONTENT_MARKER):
        return clean[:limit]
    available = limit - len(_OMITTED_CONTENT_MARKER)
    head_chars = available // 2
    tail_chars = available - head_chars
    return f"{clean[:head_chars]}{_OMITTED_CONTENT_MARKER}{clean[-tail_chars:]}"


def _append_document_tag(out: list[DocumentTag], *, tag_type: DocumentTagType, value: str) -> None:
    normalized = value.strip(" \t\r\n，,。.;；:：")
    if not normalized:
        return
    key = (tag_type, normalized.casefold())
    if any((item.type, item.value.casefold()) == key for item in out):
        return
    out.append(
        DocumentTag(
            type=tag_type,
            value=normalized,
            label=DOCUMENT_TAG_LABELS[tag_type],
            confidence=_DEFAULT_CONFIDENCE,
            source="llm",
        )
    )


def _normalize_document_tags(raw: _TaggerResponse, *, max_items: int) -> list[DocumentTag]:
    if max_items <= 0:
        return []
    out: list[DocumentTag] = []
    tag_groups: tuple[tuple[list[str], DocumentTagType], ...] = (
        (raw.topics, "topic"),
        (raw.categories, "category"),
        (raw.keywords_semantic, "keyword"),
        (raw.quality_signals, "quality"),
    )
    for values, tag_type in tag_groups:
        for value in values:
            _append_document_tag(out, tag_type=tag_type, value=value)
            if len(out) >= max_items:
                return out

    scalar_tags: tuple[tuple[str | None, DocumentTagType], ...] = (
        (raw.domain, "domain"),
        (raw.industry, "industry"),
        (raw.doc_type, "doc_type"),
        (raw.sensitivity, "sensitivity"),
    )
    for value, tag_type in scalar_tags:
        if value is not None:
            _append_document_tag(out, tag_type=tag_type, value=value)
        if len(out) >= max_items:
            return out
    return out


def _normalize_span_annotations(raw: _TaggerResponse, *, max_items: int) -> list[SpanAnnotation]:
    if max_items <= 0:
        return []
    out: list[SpanAnnotation] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw.annotations:
        label = item.label.strip() if item.label is not None else ""
        if not label:
            label = DOCUMENT_TAG_LABELS.get(item.type, "文档重点")
        key = (item.text.casefold(), item.type, label.casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            SpanAnnotation(text=item.text, type=item.type, label=label, confidence=item.confidence, source="llm")
        )
        if len(out) >= max_items:
            break
    return out


async def extract_llm_tags(
    *,
    text: str,
    llm_client: BaseLLMClient | None = None,
    model: str | None = None,
    max_chars: int = 3000,
    max_items: int = 16,
) -> TaggingResult:
    context = build_tagger_context(text, max_chars=max_chars)
    model_config = {"model": model} if model else None
    async with AsyncExitStack() as resources:
        llm = llm_client
        if llm is None:
            llm = await create_llm_client(model_config=model_config)
            resources.push_async_callback(llm.aclose)
        response = await llm.chat_with_schema(
            [
                LLMMessage(role=LLMRole.SYSTEM, content=AUTO_TAGGER_SYSTEM_PROMPT),
                LLMMessage(role=LLMRole.USER, content=f"原文：\n{context}"),
            ],
            response_schema=AUTO_TAGGER_RESPONSE_SCHEMA,
            temperature=0.0,
            max_tokens=1200,
        )
    raw = _TaggerResponse.model_validate(response)
    return TaggingResult(
        summary=raw.summary,
        document_tags=_normalize_document_tags(raw, max_items=max_items),
        span_annotations=_normalize_span_annotations(raw, max_items=max_items),
        provider="llm",
    )


__all__ = ["build_tagger_context", "extract_llm_tags"]
