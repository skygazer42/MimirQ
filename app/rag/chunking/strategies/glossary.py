"""
Glossary / dictionary entry-aware chunking strategy.

Targets documents that look like term-definition lists, e.g.:
- Term: definition...
- 术语：定义...
- Term - definition...

The chunker tries to keep a full entry together and uses entry-level overlap.
"""


from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Entry:
    start: int
    end: int
    term: str


_EN_TERM_ALLOWED_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _./+()-")


def _is_all_cjk(s: str) -> bool:
    t = str(s or "")
    if not t:
        return False
    for ch in t:
        code = ord(ch)
        if not (0x4E00 <= code <= 0x9FFF):
            return False
    return True


def _find_entry_separator(s: str) -> tuple[int, int] | None:
    idx_ascii = s.find(":")
    idx_full = s.find("：")
    separator_index = _min_nonnegative_index(idx_ascii, idx_full)
    if separator_index is not None:
        return separator_index, 1

    for token in (" - ", " – ", " — "):
        token_index = s.find(token)
        if token_index >= 0:
            return token_index, len(token)
    return None


def _min_nonnegative_index(*indexes: int) -> int | None:
    valid = [index for index in indexes if index >= 0]
    return min(valid) if valid else None


def _valid_term_from_parts(term: str, definition: str) -> str | None:
    if not term or not definition:
        return None
    if len(term) > 60 or term.count(" ") > 6:
        return None
    if _is_all_cjk(term) and (2 <= len(term) <= 20):
        return term
    if not (term[:1].isascii() and term[:1].isalpha()):
        return None
    if any(ch not in _EN_TERM_ALLOWED_CHARS for ch in term):
        return None
    return term


def _parse_inline_entry(line: str) -> str | None:
    """
    Best-effort parser for glossary lines like:
      Term: definition...
      术语：定义...
      Term - definition...

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    s = str(line or "").strip()
    if not s:
        return None

    separator = _find_entry_separator(s)
    if separator is None:
        return None
    sep_idx, sep_len = separator
    if sep_idx <= 0:
        return None

    term = s[:sep_idx].strip()
    definition = s[sep_idx + sep_len :].strip()
    return _valid_term_from_parts(term, definition)


def _iter_entries(text: str) -> list[_Entry]:
    if not text:
        return []

    starts: list[int] = []
    terms: list[str] = []
    offset = 0
    for raw_line in (text or "").splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)
        term = _parse_inline_entry(raw_line)
        if not term:
            continue
        starts.append(int(line_start))
        terms.append(term)

    if len(starts) < 2:
        return []

    entries: list[_Entry] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(text)
        entries.append(_Entry(start=int(start), end=int(end), term=terms[idx]))

    return entries if len(entries) >= 2 else []


def looks_like_glossary(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    entries = _iter_entries(text)
    return len(entries) >= 5


def _split_glossary_fallback_docs(splitter: RecursiveCharacterTextSplitter, text: str, base_meta: dict[str, Any]) -> list[Document]:
    split_docs = splitter.create_documents(texts=[text], metadatas=[base_meta])
    chunks: list[Document] = []
    for split_doc in split_docs:
        split_meta = dict(split_doc.metadata or {})
        abs_start = int(split_meta.pop("start_index", None) or 0)
        meta: dict[str, Any] = dict(base_meta)
        meta.update(split_meta)
        meta["chunk_strategy"] = "glossary"
        meta["start_char"] = abs_start
        meta["end_char"] = abs_start + len(split_doc.page_content)
        meta["glossary_fallback"] = True
        chunks.append(Document(page_content=split_doc.page_content, metadata=meta))
    return chunks


def _glossary_window_end(entries: list[_Entry], start_idx: int, chunk_size: int) -> int:
    end_idx = start_idx
    while end_idx < len(entries):
        candidate_len = entries[end_idx].end - entries[start_idx].start
        if end_idx == start_idx or candidate_len <= chunk_size:
            end_idx += 1
            continue
        break
    return end_idx if end_idx > start_idx else start_idx + 1


def _window_glossary_terms(entries: list[_Entry], start_idx: int, end_idx: int) -> list[str]:
    uniq_terms: list[str] = []
    for entry in entries[start_idx:end_idx]:
        if entry.term not in uniq_terms:
            uniq_terms.append(entry.term)
    return uniq_terms[:8]


def _build_glossary_chunk(entries: list[_Entry], start_idx: int, end_idx: int, base_meta: dict[str, Any], text: str) -> Document:
    chunk_start = entries[start_idx].start
    chunk_end = entries[end_idx - 1].end
    meta: dict[str, Any] = dict(base_meta)
    meta["chunk_strategy"] = "glossary"
    meta["start_char"] = chunk_start
    meta["end_char"] = chunk_end
    meta["glossary_entry_count"] = int(end_idx - start_idx)
    terms = _window_glossary_terms(entries, start_idx, end_idx)
    if terms:
        meta["glossary_terms"] = terms
    return Document(page_content=text[chunk_start:chunk_end], metadata=meta)


def _next_glossary_start(entries: list[_Entry], start_idx: int, end_idx: int, chunk_overlap: int) -> int:
    next_start = end_idx
    if chunk_overlap <= 0 or (end_idx - start_idx) <= 1:
        return next_start

    desired = end_idx - 1
    while desired > start_idx:
        overlap_len = entries[end_idx - 1].end - entries[desired - 1].start
        if overlap_len <= chunk_overlap:
            desired -= 1
            continue
        break
    next_start = desired if desired > start_idx else (end_idx - 1)
    return next_start if next_start > start_idx else end_idx


class GlossaryChunker(BaseChunker):
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
            out.extend(self._split_document(doc))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

    def _split_document(self, doc: Document) -> list[Document]:
        text = doc.page_content or ""
        if not text.strip():
            return []

        base_meta = dict(doc.metadata or {})
        entries = _iter_entries(text)
        if not entries:
            return _split_glossary_fallback_docs(self._fallback_splitter, text, base_meta)

        chunks: list[Document] = []
        start_idx = 0
        while start_idx < len(entries):
            end_idx = _glossary_window_end(entries, start_idx, self.chunk_size)
            chunks.append(_build_glossary_chunk(entries, start_idx, end_idx, base_meta, text))
            start_idx = _next_glossary_start(entries, start_idx, end_idx, self.chunk_overlap)
        return chunks
