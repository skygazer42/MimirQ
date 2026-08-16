
import re
from typing import Any, Callable

from langchain_core.documents import Document

from app.rag.retrieval.hybrid.common import (
    _DISPLAY_METADATA_KEY,
    _EVALUABLE_METADATA_KEY,
    _RETRIEVAL_DISPLAY_CONTENT_KEY,
    _RETRIEVAL_QUESTIONS_CHANNEL_KEY,
    _RETRIEVAL_TEXT_KEY,
)


def normalize_document_questions(value: Any, *, max_items: int = 5) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text[:200])
        if len(out) >= max(1, int(max_items or 1)):
            break
    return out


def _format_metadata_view_value(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""

    def _clean(raw: Any) -> str:
        return re.sub(r"\s+", " ", str(raw).strip())

    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for item in value:
            cleaned = _clean(item)
            if cleaned:
                parts.append(cleaned)
        return ", ".join(parts[:5])
    if isinstance(value, dict):
        parts = []
        for k, v in sorted(value.items(), key=lambda item: str(item[0])):
            if v in (None, "", [], {}):
                continue
            cleaned_key = _clean(k)
            cleaned_value = _clean(v)
            if cleaned_key and cleaned_value:
                parts.append(f"{cleaned_key}={cleaned_value}")
        return ", ".join(parts[:5])
    return _clean(value)


def _metadata_view_header_lines(metadata: dict[str, Any], *, max_fields: int = 12) -> list[str]:
    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for view_key in (_DISPLAY_METADATA_KEY, _EVALUABLE_METADATA_KEY):
        view = metadata.get(view_key)
        if not isinstance(view, dict):
            continue
        for raw_key, raw_value in sorted(view.items(), key=lambda item: str(item[0])):
            key = str(raw_key).strip()
            if not key:
                continue
            value = _format_metadata_view_value(raw_value)
            if not value:
                continue
            marker = (key, value)
            if marker in seen:
                continue
            seen.add(marker)
            lines.append(f"- {key}: {value[:200]}")
            if len(lines) >= max(1, int(max_fields or 1)):
                return lines
    return lines


def rerank_text_from_result(result: dict[str, Any]) -> str:
    content = str(result.get("content") or "").strip()
    metadata = result.get("metadata") if isinstance(result, dict) else None
    if not isinstance(metadata, dict):
        return content
    lines = _metadata_view_header_lines(metadata)
    if not lines:
        return content
    header = "Metadata:\n" + "\n".join(lines)
    if not content:
        return header
    return f"{header}\n\n{content}"


def augment_retrieval_corpus_text(*, content: str, metadata: dict[str, Any]) -> tuple[str, bool]:
    base = str(content or "")
    if bool(metadata.get("rich_metadata_header_applied")):
        return base, False

    questions = normalize_document_questions(metadata.get("document_questions"))
    if not questions:
        return base, False

    base_folded = base.casefold()
    additions = [question for question in questions if question.casefold() not in base_folded]
    if not additions:
        return base, False

    question_block = "Questions:\n" + "\n".join(f"- {question}" for question in additions)
    if not base.strip():
        return question_block, True
    return f"{base.rstrip()}\n\n{question_block}", True


def prepare_retrieval_document(
    doc: Document,
    *,
    log_fallback: Callable[[str, Exception], None],
) -> Document:
    meta = dict(doc.metadata or {})
    display_content = str(meta.get(_RETRIEVAL_DISPLAY_CONTENT_KEY) or doc.page_content or "")
    indexed_content = meta.get(_RETRIEVAL_TEXT_KEY)
    retrieval_base = (
        str(indexed_content)
        if isinstance(indexed_content, str) and indexed_content.strip()
        else display_content
    )
    retrieval_content, applied = augment_retrieval_corpus_text(content=retrieval_base, metadata=meta)
    meta[_RETRIEVAL_DISPLAY_CONTENT_KEY] = display_content
    meta[_RETRIEVAL_QUESTIONS_CHANNEL_KEY] = bool(applied)
    try:
        return doc.model_copy(update={"page_content": retrieval_content, "metadata": meta})
    except Exception as exc:
        log_fallback("_prepare_retrieval_document", exc)
        return Document(page_content=retrieval_content, metadata=meta, id=getattr(doc, "id", None))


def question_channel_overlap_score(
    *,
    query_tokens: list[str],
    metadata: dict[str, Any],
    tokenize: Callable[[str], list[str]],
) -> float:
    questions = normalize_document_questions(metadata.get("document_questions"))
    if not questions or not query_tokens:
        return 0.0
    question_tokens = set(tokenize(" ".join(questions)))
    if not question_tokens:
        return 0.0
    overlap = set(query_tokens) & question_tokens
    if not overlap:
        return 0.0
    return min(1.0, float(len(overlap)) / float(max(1, len(set(query_tokens)))))
