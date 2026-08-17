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

import re
from typing import Any

from langchain_core.documents import Document

from app.rag.preprocessing.frontmatter import extract_markdown_frontmatter, extract_markdown_title
from app.rag.preprocessing.keyword import extract_keywords
from app.rag.preprocessing.language import detect_language

_SCHEMA = "mimirq.metadata_enrichment.v1"
_WHITESPACE_RE = re.compile(r"\s+")


def _safe_text(value: Any, *, max_len: int = 500) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[: max(1, int(max_len or 1))]


def _safe_str_list(value: Any, *, max_items: int, max_len: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _safe_text(item, max_len=max_len)
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
    return _WHITESPACE_RE.sub(" ", str(text or "").strip()).strip()


def _strip_leading_title(text: str, *, title: str | None) -> str:
    raw = str(text or "")
    title_norm = _normalize_space(title or "")
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
    raw = str(text or "").strip()
    if not raw:
        return None
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    if not paragraphs:
        return None
    summary = _normalize_space(paragraphs[0])
    if len(summary) > max_chars:
        summary = summary[: max_chars - 3].rstrip() + "..."
    return summary or None


def _build_questions(
    *,
    title: str | None,
    summary: str | None,
    keywords: list[str],
    language: str | None,
    count: int,
) -> list[str]:
    count = max(1, int(count or 1))
    title_text = _safe_text(title, max_len=120)
    summary_text = _safe_text(summary, max_len=180)
    topic = title_text or (keywords[0] if keywords else "this document")
    topic_secondary = keywords[1] if len(keywords) > 1 else topic
    is_zh = str(language or "").strip().lower() in {"zh", "mixed"}

    candidates: list[str]
    if is_zh:
        candidates = [
            f"{topic} 主要讲什么？",
            f"如何配置或使用 {topic_secondary}？",
            f"{topic} 提供了哪些关键步骤或注意事项？",
            f"{topic} 中有哪些重要参数或术语？",
        ]
        if summary_text:
            candidates.append(f"根据文档摘要，{topic} 的核心结论是什么？")
    else:
        candidates = [
            f"What does {topic} describe?",
            f"How is {topic_secondary} configured or used?",
            f"What are the key steps or considerations in {topic}?",
            f"Which important terms or parameters are covered in {topic}?",
        ]
        if summary_text:
            candidates.append(f"Based on the summary, what are the main takeaways from {topic}?")

    out: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        question = _safe_text(item, max_len=200)
        if not question:
            continue
        key = question.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(question)
        if len(out) >= count:
            break
    return out


def _frontmatter_data(frontmatter: object) -> dict[str, Any]:
    data = getattr(frontmatter, "data", None)
    return data if isinstance(data, dict) else {}


def _resolve_title(meta: dict[str, Any], frontmatter: object, working: str) -> str | None:
    title = _safe_text(meta.get("document_title"), max_len=200)
    data = _frontmatter_data(frontmatter)
    if not title:
        title = _safe_text(data.get("title"), max_len=200)
    if not title:
        title = _safe_text(extract_markdown_title(working), max_len=200)
    return title


def _resolve_tags(meta: dict[str, Any], frontmatter: object) -> list[str]:
    tags = _safe_str_list(meta.get("document_tags"), max_items=20, max_len=64)
    if tags:
        return tags
    return _safe_str_list(_frontmatter_data(frontmatter).get("tags"), max_items=20, max_len=64)


def _resolve_summary(meta: dict[str, Any], working: str, title: str | None, max_chars: int) -> str | None:
    summary = _safe_text(meta.get("document_summary"), max_len=max_chars)
    if summary:
        return summary
    return _summary_from_text(_strip_leading_title(working, title=title), max_chars=max_chars)


def _resolve_language(meta: dict[str, Any], working: str) -> tuple[str | None, Any]:
    language = _safe_text(meta.get("document_language"), max_len=20)
    language_confidence = meta.get("document_language_confidence")
    if language:
        return language, language_confidence
    try:
        detected = detect_language(working, min_chars=20)
        language = _safe_text(getattr(detected, "language", None), max_len=20)
        language_confidence = round(float(getattr(detected, "confidence", 0.0) or 0.0), 3)
    except Exception:
        language = None
        language_confidence = None
    return language, language_confidence


def _resolve_keywords(
    meta: dict[str, Any],
    working: str,
    *,
    provider: str,
    top_k: int,
    max_chars: int,
) -> tuple[list[str], str | None]:
    item_limit = max(1, int(top_k or 1))
    keywords = _safe_str_list(meta.get("document_keywords"), max_items=item_limit, max_len=64)
    provider_out = _safe_text(meta.get("document_keywords_provider"), max_len=50)
    if keywords:
        return keywords, provider_out
    try:
        snippet = working[: max(0, int(max_chars or 0))] if int(max_chars or 0) > 0 else working
        keywords = _safe_str_list(
            extract_keywords(
                snippet,
                provider=str(provider or "auto"),
                top_k=item_limit,
            ),
            max_items=item_limit,
            max_len=64,
        )
        if keywords:
            provider_out = str(provider or "auto")[:50]
    except Exception:
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
    item_limit = max(1, int(count or 1))
    questions = _safe_str_list(meta.get("document_questions"), max_items=item_limit, max_len=200)
    if questions or not bool(generate):
        return questions
    return _build_questions(
        title=title,
        summary=summary,
        keywords=keywords,
        language=language,
        count=item_limit,
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
    language_confidence: Any,
    frontmatter: object,
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
        out["document_keywords_provider"] = keywords_provider_out or str(keywords_provider or "auto")[:50]
    if questions:
        out["document_questions"] = questions
    if language:
        out["document_language"] = language
        if isinstance(language_confidence, (int, float)):
            out["document_language_confidence"] = round(float(language_confidence), 3)
    if frontmatter and isinstance(frontmatter.data, dict) and frontmatter.data:
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
    meta = dict(metadata or {})
    raw = str(text or "")
    if not raw.strip():
        return {}

    frontmatter = extract_markdown_frontmatter(raw, strip=True)
    working = str(frontmatter.stripped_text if frontmatter else raw).strip()

    title = _resolve_title(meta, frontmatter, working)
    tags = _resolve_tags(meta, frontmatter)
    summary = _resolve_summary(meta, working, title, summary_max_chars)
    language, language_confidence = _resolve_language(meta, working)

    keywords, keywords_provider_out = _resolve_keywords(
        meta,
        working,
        provider=keywords_provider,
        top_k=keyword_top_k,
        max_chars=keyword_max_chars,
    )
    questions = _resolve_questions(
        meta,
        title=title,
        summary=summary,
        keywords=keywords,
        language=language,
        count=question_count,
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
    meta = dict(metadata or {})
    title = _safe_text(meta.get("document_title"), max_len=200)
    summary = _safe_text(meta.get("document_summary"), max_len=240)
    keywords = _safe_str_list(meta.get("document_keywords"), max_items=max_keywords, max_len=64)
    questions = _safe_str_list(meta.get("document_questions"), max_items=max_questions, max_len=200)

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
    for doc in documents or []:
        meta = dict(doc.metadata or {})
        meta.update(
            build_document_metadata_enrichment(
                doc.page_content or "",
                metadata=meta,
                keywords_provider=keywords_provider,
                keyword_top_k=keyword_top_k,
                keyword_max_chars=keyword_max_chars,
                summary_max_chars=summary_max_chars,
                question_count=question_count,
                generate_questions=generate_questions,
            )
        )
        try:
            out.append(doc.model_copy(update={"metadata": meta}))
        except Exception:
            out.append(Document(page_content=doc.page_content or "", metadata=meta, id=getattr(doc, "id", None)))
    return out


__all__ = [
    "build_document_metadata_enrichment",
    "build_rich_metadata_header",
    "enrich_documents_metadata",
]
