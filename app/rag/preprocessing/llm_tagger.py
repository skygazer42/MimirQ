
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.rag.llm.factory import create_llm_client
from app.rag.llm.models import LLMMessage, LLMRole
from app.rag.llm.prompts.tagger_prompts import AUTO_TAGGER_RESPONSE_SCHEMA, AUTO_TAGGER_SYSTEM_PROMPT

DocumentTagType = Literal["topic", "category", "domain", "industry", "doc_type", "sensitivity", "quality", "keyword"]
SpanAnnotationType = Literal["entity", "keyword", "sensitive", "custom"]

_DOCUMENT_TAG_LABELS: dict[str, str] = {
    "topic": "主题",
    "category": "分类",
    "domain": "领域",
    "industry": "行业",
    "doc_type": "文档类型",
    "sensitivity": "敏感度",
    "quality": "质量线索",
    "keyword": "语义关键词",
}
_ALLOWED_SPAN_TYPES = {"entity", "keyword", "sensitive", "custom"}


class LLMDocumentTag(BaseModel):
    type: DocumentTagType
    value: str = Field(..., min_length=1, max_length=120)
    label: str = Field(default="")
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    source: str = Field(default="llm", max_length=64)


class LLMSpanAnnotation(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    type: SpanAnnotationType = "custom"
    label: str = Field(default="文档重点", min_length=1, max_length=80)
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    source: str = Field(default="llm", max_length=64)


class LLMTaggingResult(BaseModel):
    summary: str | None = Field(default=None, max_length=1000)
    document_tags: list[LLMDocumentTag] = Field(default_factory=list)
    span_annotations: list[LLMSpanAnnotation] = Field(default_factory=list)
    provider: str = "llm"


def build_tagger_context(text: str, *, max_chars: int = 3000) -> str:
    clean = str(text or "").strip()
    max_chars_i = max(200, int(max_chars or 3000))
    if len(clean) <= max_chars_i:
        return clean

    head_chars = max_chars_i // 2
    tail_chars = max_chars_i - head_chars
    return f"{clean[:head_chars]}\n\n[... omitted middle content ...]\n\n{clean[-tail_chars:]}"


def _iter_text_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_iter_text_values(item))
        return out
    if isinstance(value, dict):
        for key in ("value", "text", "name", "label"):
            text = str(value.get(key) or "").strip()
            if text:
                return [text]
    text = str(value or "").strip()
    return [text] if text else []


def _coerce_confidence(value: Any, default: float = 0.85) -> float:
    try:
        score = float(value)
    except Exception:
        score = default
    return min(1.0, max(0.0, score))


def _append_document_tag(
    out: list[LLMDocumentTag],
    *,
    tag_type: DocumentTagType,
    value: str,
    confidence: float = 0.85,
) -> None:
    normalized = str(value or "").strip(" \t\r\n，,。.;；:：")
    if not normalized:
        return
    key = (tag_type, normalized.casefold())
    if any((item.type, item.value.casefold()) == key for item in out):
        return
    out.append(
        LLMDocumentTag(
            type=tag_type,
            value=normalized,
            label=_DOCUMENT_TAG_LABELS[tag_type],
            confidence=_coerce_confidence(confidence),
            source="llm",
        )
    )


def _normalize_document_tags(raw: dict[str, Any], *, max_items: int) -> list[LLMDocumentTag]:
    out: list[LLMDocumentTag] = []
    for field, tag_type in (
        ("topics", "topic"),
        ("categories", "category"),
        ("keywords_semantic", "keyword"),
        ("quality_signals", "quality"),
    ):
        for value in _iter_text_values(raw.get(field)):
            _append_document_tag(out, tag_type=tag_type, value=value)
            if len(out) >= max_items:
                return out

    for field, tag_type in (
        ("domain", "domain"),
        ("industry", "industry"),
        ("doc_type", "doc_type"),
        ("sensitivity", "sensitivity"),
    ):
        for value in _iter_text_values(raw.get(field)):
            _append_document_tag(out, tag_type=tag_type, value=value)
            break
        if len(out) >= max_items:
            return out
    return out[:max_items]


def _normalize_span_annotations(raw: dict[str, Any], *, max_items: int) -> list[LLMSpanAnnotation]:
    annotations = raw.get("annotations")
    if not isinstance(annotations, list):
        return []

    out: list[LLMSpanAnnotation] = []
    seen: set[tuple[str, str, str]] = set()
    for item in annotations:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        raw_type = str(item.get("type") or "custom").strip().lower()
        annotation_type = raw_type if raw_type in _ALLOWED_SPAN_TYPES else "custom"
        label = str(item.get("label") or _DOCUMENT_TAG_LABELS.get(annotation_type, "文档重点")).strip() or "文档重点"
        key = (text.casefold(), annotation_type, label.casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            LLMSpanAnnotation(
                text=text,
                type=annotation_type,  # type: ignore[arg-type]
                label=label,
                confidence=_coerce_confidence(item.get("confidence"), default=0.85),
                source="llm",
            )
        )
        if len(out) >= max_items:
            break
    return out


async def extract_llm_tags(
    *,
    text: str,
    llm_client: Any | None = None,
    model: str | None = None,
    max_chars: int = 3000,
    max_items: int = 16,
) -> LLMTaggingResult:
    context = build_tagger_context(text, max_chars=max_chars)
    model_config = {"model": model} if model else None
    llm = llm_client or await create_llm_client(scenario="governance_auto_tagging", model_config=model_config)
    raw = await llm.chat_with_schema(
        [
            LLMMessage(role=LLMRole.SYSTEM, content=AUTO_TAGGER_SYSTEM_PROMPT),
            LLMMessage(role=LLMRole.USER, content=f"原文：\n{context}"),
        ],
        response_schema=AUTO_TAGGER_RESPONSE_SCHEMA,
        temperature=0.0,
        max_tokens=1200,
    )
    if not isinstance(raw, dict):
        raw = {}

    summary = str(raw.get("summary") or "").strip() or None
    document_tags = _normalize_document_tags(raw, max_items=max(1, int(max_items or 16)))
    span_annotations = _normalize_span_annotations(raw, max_items=max(1, int(max_items or 16)))
    return LLMTaggingResult(
        summary=summary,
        document_tags=document_tags,
        span_annotations=span_annotations,
        provider="llm",
    )


__all__ = [
    "LLMDocumentTag",
    "LLMSpanAnnotation",
    "LLMTaggingResult",
    "build_tagger_context",
    "extract_llm_tags",
]
