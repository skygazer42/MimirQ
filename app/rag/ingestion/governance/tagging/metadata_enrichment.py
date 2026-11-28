"""
Document metadata enrichment helpers.

This module provides a deterministic, dependency-light baseline for:
- document summary
- document keywords
- suggested answerable questions

It is intentionally heuristic-first so it can be used in indexing, chunking,
tests, and offline jobs without requiring an LLM. A future LLM-backed path can
layer on top of the same output schema.
"""

import logging
import re
from typing import Any

from langchain_core.documents import Document

from app.rag.ingestion.governance.markup.frontmatter import (
    FrontmatterExtractResult,
    extract_markdown_frontmatter,
    extract_markdown_title,
)
from app.rag.ingestion.governance.tagging.keyword import extract_keywords
from app.rag.ingestion.governance.tagging.language import detect_language

_SCHEMA = "mimirq.metadata_enrichment.v1"
_WHITESPACE_RE = re.compile(r"\s+")
logger = logging.getLogger(__name__)
_ENRICHMENT_FIELDS = frozenset(
    {
        "document_title",
        "document_tags",
        "document_summary",
        "document_keywords",
        "document_keywords_provider",
        "document_questions",
        "document_language",
        "document_language_confidence",
    }
)


def _metadata_text(value: Any, *, max_len: int = 500) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text[:max_len]


def _metadata_text_list(value: Any, *, max_items: int, max_len: int) -> list[str]:
    if max_items <= 0 or not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _metadata_text(item, max_len=max_len)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= max_items:
            break
    return out


def _normalize_space(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.strip())


def _strip_leading_title(text: str, *, title: str | None) -> str:
    raw = text
    title_norm = _normalize_space(title) if title is not None else ""
    if not raw.strip() or not title_norm:
        return raw.strip()
    lines = raw.splitlines()
    kept: list[str] = []
    skipped = False
    for line in lines:
        stripped = line.strip()
        if not skipped and stripped:
            candidate = stripped.lstrip("#").strip()
            if _normalize_space(candidate).casefold() == title_norm.casefold():
                skipped = True
                continue
            skipped = True
        kept.append(line)
    return "\n".join(kept).strip()


def _summary_from_text(text: str, *, max_chars: int) -> str | None:
    raw = text.strip()
    if not raw:
        return None
    summary = _normalize_space(re.split(r"\n\s*\n", raw, maxsplit=1)[0])
    if len(summary) > max_chars:
        summary = summary[: max_chars - 3].rstrip() + "..." if max_chars > 3 else summary[:max_chars]
    return summary


def _build_questions(
    *,
    title: str | None,
    summary: str | None,
    keywords: list[str],
    language: str | None,
    count: int,
) -> list[str]:
    title_text = title[:120] if title is not None else None
    topic = title_text or (keywords[0] if keywords else "this document")
    topic_secondary = keywords[1] if len(keywords) > 1 else topic
    is_zh = language is not None and language.strip().lower() in {"zh", "mixed"}

    candidates: list[str]
    if is_zh:
        candidates = [
            f"{topic} 主要讲什么？",
            f"如何配置或使用 {topic_secondary}？",
            f"{topic} 提供了哪些关键步骤或注意事项？",
            f"{topic} 中有哪些重要参数或术语？",
        ]
        if summary:
            candidates.append(f"根据文档摘要，{topic} 的核心结论是什么？")
    else:
        candidates = [
            f"What does {topic} describe?",
            f"How is {topic_secondary} configured or used?",
            f"What are the key steps or considerations in {topic}?",
            f"Which important terms or parameters are covered in {topic}?",
        ]
        if summary:
            candidates.append(f"Based on the summary, what are the main takeaways from {topic}?")

    return [question[:200] for question in candidates[:count]]


def _resolve_title(meta: dict[str, Any], frontmatter: FrontmatterExtractResult | None, working: str) -> str | None:
    title = _metadata_text(meta.get("document_title"), max_len=200)
    data = frontmatter.data if frontmatter is not None else {}
    if not title:
        title = _metadata_text(data.get("title"), max_len=200)
    if not title:
        title = _metadata_text(extract_markdown_title(working), max_len=200)
    return title


def _resolve_tags(meta: dict[str, Any], frontmatter: FrontmatterExtractResult | None) -> list[str]:
    tags = _metadata_text_list(meta.get("document_tags"), max_items=20, max_len=64)
    if tags:
        return tags
    data = frontmatter.data if frontmatter is not None else {}
    return _metadata_text_list(data.get("tags"), max_items=20, max_len=64)


def _resolve_summary(meta: dict[str, Any], working: str, title: str | None, max_chars: int) -> str | None:
    if max_chars <= 0:
        return None
    summary = _metadata_text(meta.get("document_summary"), max_len=max_chars)
    if summary:
        return summary
    return _summary_from_text(_strip_leading_title(working, title=title), max_chars=max_chars)


def _resolve_language(meta: dict[str, Any], working: str) -> tuple[str, float | None]:
    language = _metadata_text(meta.get("document_language"), max_len=20)
    language_confidence = meta.get("document_language_confidence")
    if language:
        if (
            isinstance(language_confidence, (int, float))
            and not isinstance(language_confidence, bool)
            and 0 <= language_confidence <= 1
        ):
            return language, float(language_confidence)
        if language_confidence is not None:
            logger.warning("Ignoring invalid document language confidence: %s", type(language_confidence).__name__)
        return language, None
    detected = detect_language(working, min_chars=20)
    return detected.language, round(detected.confidence, 3)


def _resolve_keywords(
    meta: dict[str, Any],
    working: str,
    *,
    provider: str,
    top_k: int,
    max_chars: int,
) -> tuple[list[str], str | None]:
    keywords = _metadata_text_list(meta.get("document_keywords"), max_items=top_k, max_len=64)
    provider_out = _metadata_text(meta.get("document_keywords_provider"), max_len=50)
    if keywords:
        return keywords, provider_out
    try:
        snippet = working[:max_chars] if max_chars > 0 else working
        keywords = _metadata_text_list(
            extract_keywords(
                snippet,
                provider=provider,
                top_k=top_k,
            ),
            max_items=top_k,
            max_len=64,
        )
        if keywords:
            provider_out = provider[:50]
    except Exception as exc:
        logger.warning("Optional metadata keyword extraction failed: %s", type(exc).__name__)
        keywords = []
    return keywords, provider_out


def _resolve_questions(
    meta: dict[str, Any],
    *,
    title: str | None,
    summary: str | None,
    keywords: list[str],
    language: str | None,
    count: int,
    generate: bool,
) -> list[str]:
    questions = _metadata_text_list(meta.get("document_questions"), max_items=count, max_len=200)
    if questions or not generate:
        return questions
    return _build_questions(
        title=title,
        summary=summary,
        keywords=keywords,
        language=language,
        count=count,
    )


def _build_enrichment_output(
    *,
    title: str | None,
    tags: list[str],
    summary: str | None,
    keywords: list[str],
    keywords_provider_out: str | None,
    keywords_provider: str,
    questions: list[str],
    language: str | None,
    language_confidence: float | None,
    frontmatter: FrontmatterExtractResult | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"metadata_enrichment_schema": _SCHEMA}
    if title:
        out["document_title"] = title
    if tags:
        out["document_tags"] = tags
    if summary:
        out["document_summary"] = summary
    if keywords:
        out["document_keywords"] = keywords
        out["document_keywords_provider"] = keywords_provider_out or keywords_provider[:50]
    if questions:
        out["document_questions"] = questions
    if language:
        out["document_language"] = language
        if language_confidence is not None:
            out["document_language_confidence"] = round(language_confidence, 3)
    if frontmatter is not None and frontmatter.data:
        out["document_frontmatter"] = dict(frontmatter.data)
    return out


def build_document_metadata_enrichment(
    text: str,
    *,
    metadata: dict[str, Any] | None = None,
    keywords_provider: str = "auto",
    keyword_top_k: int = 8,
    keyword_max_chars: int = 4000,
    summary_max_chars: int = 220,
    question_count: int = 3,
    generate_questions: bool = True,
) -> dict[str, Any]:
    """
    Build deterministic document-level enrichment fields.

    Output fields intentionally align with existing document metadata naming:
    - document_title
    - document_tags
    - document_summary
    - document_keywords
    - document_keywords_provider
    - document_questions
    - document_language
    - document_language_confidence
    """
    meta = {} if metadata is None else metadata
    raw = text
    if not raw.strip():
        return {}

    frontmatter = extract_markdown_frontmatter(raw, strip=True)
    working = (frontmatter.stripped_text if frontmatter is not None else raw).strip()

    title = _resolve_title(meta, frontmatter, working)
    tags = _resolve_tags(meta, frontmatter)
    summary = _resolve_summary(meta, working, title, summary_max_chars)
    language, language_confidence = _resolve_language(meta, working)

    keywords, keywords_provider_out = _resolve_keywords(
        meta,
        working,
        provider=keywords_provider,
        top_k=max(1, keyword_top_k),
        max_chars=keyword_max_chars,
    )
    questions = _resolve_questions(
        meta,
        title=title,
        summary=summary,
        keywords=keywords,
        language=language,
        count=max(1, question_count),
        generate=generate_questions,
    )
    return _build_enrichment_output(
        title=title,
        tags=tags,
        summary=summary,
        keywords=keywords,
        keywords_provider_out=keywords_provider_out,
        keywords_provider=keywords_provider,
        questions=questions,
        language=language,
        language_confidence=language_confidence,
        frontmatter=frontmatter,
    )


def build_rich_metadata_header(
    metadata: dict[str, Any] | None,
    *,
    max_keywords: int = 8,
    max_questions: int = 3,
) -> str | None:
    meta = {} if metadata is None else metadata
    title = _metadata_text(meta.get("document_title"), max_len=200)
    summary = _metadata_text(meta.get("document_summary"), max_len=240)
    keywords = _metadata_text_list(meta.get("document_keywords"), max_items=max_keywords, max_len=64)
    questions = _metadata_text_list(meta.get("document_questions"), max_items=max_questions, max_len=200)

    lines: list[str] = []
    if title:
        lines.append(f"Title: {title}")
    if summary:
        lines.append(f"Summary: {summary}")
    if keywords:
        lines.append(f"Keywords: {', '.join(keywords)}")
    if questions:
        lines.append("Questions:")
        lines.extend([f"- {item}" for item in questions])
    if not lines:
        return None
    return "\n".join(lines)


def enrich_documents_metadata(
    documents: list[Document],
    *,
    keywords_provider: str = "auto",
    keyword_top_k: int = 8,
    keyword_max_chars: int = 4000,
    summary_max_chars: int = 220,
    question_count: int = 3,
    generate_questions: bool = True,
) -> list[Document]:
    out: list[Document] = []
    for doc in documents:
        meta = dict(doc.metadata)
        if summary_max_chars <= 0:
            meta.pop("document_summary", None)
        enrichment = build_document_metadata_enrichment(
            doc.page_content,
            metadata=meta,
            keywords_provider=keywords_provider,
            keyword_top_k=keyword_top_k,
            keyword_max_chars=keyword_max_chars,
            summary_max_chars=summary_max_chars,
            question_count=question_count,
            generate_questions=generate_questions,
        )
        if enrichment:
            # Replace this pass's normalized fields, retaining earlier parser provenance.
            for key in _ENRICHMENT_FIELDS:
                meta.pop(key, None)
            meta.update(enrichment)
        out.append(doc.model_copy(update={"metadata": meta}))
    return out


__all__ = [
    "build_document_metadata_enrichment",
    "build_rich_metadata_header",
    "enrich_documents_metadata",
]
