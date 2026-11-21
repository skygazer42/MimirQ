"""Prepare and render retrieved documents for generation."""

import logging
from typing import Any

from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.infrastructure.tokens import num_tokens_from_string, truncate
from app.rag.retrieval.evidence.excerpts import extract_evidence_text
from app.types.document_metadata import metadata_text

logger = logging.getLogger("rag.pipelines.langgraph")


def _build_context(docs: list[Document], *, query: str | None = None) -> str:
    """Format retrieved document context."""
    if not docs:
        return "No relevant reference materials found."

    usable_docs = _prepare_context_docs(docs, query=query)

    parts = []
    max_per_chunk_chars = max(0, int(settings.RAG_CONTEXT_MAX_CHARS_PER_CHUNK))
    max_total_chars = max(0, int(settings.RAG_CONTEXT_MAX_TOTAL_CHARS))
    max_per_chunk_tokens = max(0, int(settings.RAG_CONTEXT_MAX_TOKENS_PER_CHUNK))
    max_total_tokens = max(0, int(settings.RAG_CONTEXT_MAX_TOTAL_TOKENS))
    total_limit = max_total_tokens or max_total_chars
    measure = num_tokens_from_string if max_total_tokens else len
    total_size = 0
    for idx, doc in enumerate(usable_docs, 1):
        part = _build_context_part(
            doc,
            idx=idx,
            query=query,
            max_per_chunk_chars=max_per_chunk_chars,
            max_per_chunk_tokens=max_per_chunk_tokens,
        )
        part_size = measure(part)
        if total_limit and parts and total_size + part_size > total_limit:
            break
        parts.append(part)
        total_size += part_size
        if not max_total_tokens and max_total_chars and total_size >= max_total_chars:
            break
    return "\n\n".join(parts)


def _prepare_context_docs(docs: list[Document], *, query: str | None) -> list[Document]:
    usable_docs = _denoise_context_docs(docs)
    if settings.RAG_CONTEXT_LLM_COMPRESSION_ENABLED:
        return _compress_context_docs_with_llm(usable_docs, query=query)
    if settings.RAG_CONTEXT_COMPRESSION_ENABLED:
        usable_docs = _compress_context_docs(usable_docs, query=query)
    if settings.RAG_CONTEXT_REORDER_ENABLED:
        usable_docs = _reorder_context_docs(usable_docs)
    return usable_docs


def _denoise_context_docs(docs: list[Document]) -> list[Document]:
    try:
        from app.rag.runtime.context import denoise_context_docs

        return denoise_context_docs(docs)
    except Exception as exc:
        logger.debug("Context denoise failed, falling back to raw docs: %s", exc)
        return list(docs)


def _compress_context_docs_with_llm(docs: list[Document], *, query: str | None) -> list[Document]:
    try:
        from app.rag.llm.context_compression import compress_context_docs_with_llm

        return compress_context_docs_with_llm(docs, query=query)
    except Exception as exc:
        logger.debug("LLM context compression failed, skipping compression: %s", exc)
        return list(docs)


def _compress_context_docs(docs: list[Document], *, query: str | None) -> list[Document]:
    try:
        from app.rag.runtime.context import compress_context_docs

        return compress_context_docs(docs, query=query)
    except Exception as exc:
        logger.debug("Context compression failed, skipping compression: %s", exc)
        return list(docs)


def _reorder_context_docs(docs: list[Document]) -> list[Document]:
    try:
        from app.rag.runtime.context import reorder_docs_for_generation

        return reorder_docs_for_generation(docs)
    except Exception as exc:
        logger.debug("Context doc ordering failed, skipping reorder: %s", exc)
        return list(docs)


def _context_page_info(meta: dict[str, Any]) -> str | None:
    try:
        page_raw = meta.get("page")
        page_int = int(page_raw) if page_raw is not None else None
    except (OverflowError, TypeError, ValueError):
        return None
    if page_int and page_int > 0:
        return f"Page {page_int}"
    return None


def _context_role_info(meta: dict[str, Any]) -> str | None:
    retrieval_role = meta.get("retrieval_role")
    if retrieval_role == "neighbor":
        return "neighbor"
    if retrieval_role:
        return str(retrieval_role)
    return None


def _context_content(
    doc: Document,
    *,
    query: str | None,
    max_per_chunk_chars: int,
    max_per_chunk_tokens: int,
) -> str:
    raw_content = doc.page_content.strip()
    if settings.RAG_CONTEXT_EVIDENCE_ENABLED and query:
        return extract_evidence_text(
            raw_content,
            str(query),
            max_chars=(max_per_chunk_chars if not max_per_chunk_tokens else 0),
            max_sentences=settings.RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK,
            min_sentence_chars=settings.RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS,
        )
    if max_per_chunk_tokens:
        return truncate(raw_content, max_per_chunk_tokens)
    if max_per_chunk_chars and len(raw_content) > max_per_chunk_chars:
        return raw_content[:max_per_chunk_chars] + "..."
    return raw_content


def _build_context_part(
    doc: Document,
    *,
    idx: int,
    query: str | None,
    max_per_chunk_chars: int,
    max_per_chunk_tokens: int,
) -> str:
    meta = doc.metadata
    filename = metadata_text(meta, "filename")
    source = str(meta.get("source") or filename or "Unknown")
    info_parts: list[str] = []
    title = metadata_text(meta, "document_title") or metadata_text(meta, "doc_title") or metadata_text(meta, "title")
    if title:
        info_parts.append(f"Title: {title}")
    if filename:
        info_parts.append(f"File: {filename}")
    elif source:
        info_parts.append(source)
    for value in (
        _context_page_info(meta),
        meta.get("header_path") or meta.get("header_context"),
        _context_role_info(meta),
    ):
        if value:
            info_parts.append(str(value))
    content = _context_content(
        doc,
        query=query,
        max_per_chunk_chars=max_per_chunk_chars,
        max_per_chunk_tokens=max_per_chunk_tokens,
    )
    return f"[Source {idx}: {' | '.join(info_parts)}]\n{content}"
