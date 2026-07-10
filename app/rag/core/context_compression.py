"""Deterministic query-aware context compression helpers."""


from collections.abc import Iterable

from langchain_core.documents import Document

from app.rag.core.text import extract_evidence_text


def compress_context_docs(
    docs: Iterable[Document] | None,
    query: str | None = None,
    *,
    max_sentences: int = 3,
    min_sentence_chars: int = 10,
) -> list[Document]:
    """Compress docs into query-relevant text snippets while preserving metadata."""
    if not docs:
        return []

    out: list[Document] = []
    q = str(query or '').strip()
    for doc in docs:
        raw = str(getattr(doc, 'page_content', '') or '').strip()
        if not raw:
            continue

        content = raw
        if q:
            content = extract_evidence_text(
                raw,
                q,
                max_sentences=max(1, int(max_sentences or 0)),
                min_sentence_chars=max(0, int(min_sentence_chars or 0)),
            )
        content = str(content or '').strip()
        if not content:
            continue

        out.append(
            Document(
                page_content=content,
                metadata=dict(getattr(doc, 'metadata', None) or {}),
                id=getattr(doc, 'id', None),
            )
        )
    return out


__all__ = ['compress_context_docs']
