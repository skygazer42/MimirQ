"""
Sentence-window chunking strategy.

Splits text into sentence spans first, then groups them into chunks while:
- keeping sentence boundaries intact
- using sentence-level overlap (bounded by chunk_overlap characters)

This is useful for long plain text where character-based overlap would cut
sentences in half.
"""


import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Span:
    start: int
    end: int


_SENTENCE_RE = re.compile(r"[^。！？!?\.\\n]+[。！？!?\.\\n]?", flags=re.S)


def _iter_sentence_spans(text: str) -> list[_Span]:
    spans: list[_Span] = []
    for m in _SENTENCE_RE.finditer(text or ""):
        start, end = m.start(), m.end()
        if end <= start:
            continue
        if not (text[start:end] or "").strip():
            continue
        spans.append(_Span(start=start, end=end))
    return spans


def _append_fallback_documents(
    out: list[Document],
    split_docs: list[Document],
    base_meta: dict[str, Any],
) -> None:
    for split_doc in split_docs:
        local_start = split_doc.metadata.pop("start_index", None) or 0
        abs_start = int(local_start)
        abs_end = abs_start + len(split_doc.page_content)
        meta: dict[str, Any] = dict(base_meta)
        meta.update(split_doc.metadata or {})
        meta["chunk_strategy"] = "sentence_window"
        meta["start_char"] = abs_start
        meta["end_char"] = abs_end
        meta["sentence_window_fallback"] = True
        out.append(Document(page_content=split_doc.page_content, metadata=meta))


def _find_chunk_end(spans: list[_Span], start_idx: int, chunk_size: int) -> int:
    end_idx = start_idx
    while end_idx < len(spans):
        candidate_end = spans[end_idx].end
        candidate_len = candidate_end - spans[start_idx].start
        if end_idx == start_idx or candidate_len <= chunk_size:
            end_idx += 1
            continue
        break
    return end_idx if end_idx > start_idx else (start_idx + 1)


def _next_span_start(spans: list[_Span], start_idx: int, end_idx: int, chunk_overlap: int) -> int:
    next_start = end_idx
    if chunk_overlap > 0 and (end_idx - start_idx) > 1:
        overlap_start = end_idx - 1
        last_good = overlap_start
        while overlap_start - 1 >= start_idx:
            candidate = overlap_start - 1
            overlap_len = spans[end_idx - 1].end - spans[candidate].start
            if overlap_len <= chunk_overlap:
                overlap_start = candidate
                last_good = overlap_start
                continue
            break
        next_start = last_good
    return end_idx if next_start <= start_idx else next_start


def _assign_chunk_indexes(chunks: list[Document]) -> None:
    for idx, chunk in enumerate(chunks):
        meta = dict(chunk.metadata or {})
        meta["chunk_index"] = idx
        chunk.metadata = meta


class SentenceWindowChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "，", ". ", "!", "?", " ", ""],
            length_function=len,
            add_start_index=True,
        )

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            spans = _iter_sentence_spans(text)
            if len(spans) < 2:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                _append_fallback_documents(out, split_docs, base_meta)
                continue

            start_idx = 0
            while start_idx < len(spans):
                end_idx = _find_chunk_end(spans, start_idx, self.chunk_size)
                chunk_start = spans[start_idx].start
                chunk_end = spans[end_idx - 1].end
                content = text[chunk_start:chunk_end]

                meta: dict[str, Any] = dict(base_meta)
                meta["chunk_strategy"] = "sentence_window"
                meta["start_char"] = chunk_start
                meta["end_char"] = chunk_end
                meta["sentence_count"] = int(end_idx - start_idx)
                out.append(Document(page_content=content, metadata=meta))

                start_idx = _next_span_start(spans, start_idx, end_idx, self.chunk_overlap)

        _assign_chunk_indexes(out)

        return out
