"""
Glossary / dictionary entry-aware chunking strategy.

Targets documents that look like term-definition lists, e.g.:
- Term: definition...
- 术语：定义...
- Term - definition...

The chunker tries to keep a full entry together and uses entry-level overlap.
"""

from __future__ import annotations

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

    sep_idx: int | None = None
    sep_len = 1

    # Prefer ':' / '：' since '-' often appears inside English terms.
    idx_ascii = s.find(":")
    idx_full = s.find("：")
    if idx_ascii >= 0 and idx_full >= 0:
        sep_idx = min(idx_ascii, idx_full)
    elif idx_ascii >= 0:
        sep_idx = idx_ascii
    elif idx_full >= 0:
        sep_idx = idx_full

    if sep_idx is None:
        for token in (" - ", " – ", " — "):
            i = s.find(token)
            if i >= 0 and (sep_idx is None or i < sep_idx):
                sep_idx = i
                sep_len = len(token)

    if sep_idx is None or sep_idx <= 0:
        return None

    term = s[:sep_idx].strip()
    definition = s[sep_idx + sep_len :].strip()
    if not term or not definition:
        return None

    if len(term) > 60:
        return None
    if term.count(" ") > 6:
        return None

    # Chinese term
    if _is_all_cjk(term) and (2 <= len(term) <= 20):
        return term

    # English-ish term
    if not (term[:1].isascii() and term[:1].isalpha()):
        return None
    if any(ch not in _EN_TERM_ALLOWED_CHARS for ch in term):
        return None
    return term


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
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            entries = _iter_entries(text)
            if not entries:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "glossary"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["glossary_fallback"] = True
                    out.append(Document(page_content=sd.page_content, metadata=meta))
                continue

            start_idx = 0
            while start_idx < len(entries):
                end_idx = start_idx
                while end_idx < len(entries):
                    candidate_end = entries[end_idx].end
                    candidate_len = candidate_end - entries[start_idx].start
                    if end_idx == start_idx or candidate_len <= self.chunk_size:
                        end_idx += 1
                        continue
                    break

                if end_idx == start_idx:
                    end_idx = start_idx + 1

                chunk_start = entries[start_idx].start
                chunk_end = entries[end_idx - 1].end
                content = text[chunk_start:chunk_end]

                terms = [e.term for e in entries[start_idx:end_idx]]
                uniq_terms: list[str] = []
                for t in terms:
                    if t not in uniq_terms:
                        uniq_terms.append(t)
                uniq_terms = uniq_terms[:8]

                meta: dict[str, Any] = dict(base_meta)
                meta["chunk_strategy"] = "glossary"
                meta["start_char"] = chunk_start
                meta["end_char"] = chunk_end
                meta["glossary_entry_count"] = int(end_idx - start_idx)
                if uniq_terms:
                    meta["glossary_terms"] = uniq_terms
                out.append(Document(page_content=content, metadata=meta))

                # Entry-level overlap.
                next_start = end_idx
                if self.chunk_overlap > 0 and (end_idx - start_idx) > 1:
                    desired = end_idx - 1
                    while desired > start_idx:
                        overlap_len = entries[end_idx - 1].end - entries[desired - 1].start
                        if overlap_len <= self.chunk_overlap:
                            desired -= 1
                            continue
                        break
                    next_start = desired if desired > start_idx else (end_idx - 1)

                if next_start <= start_idx:
                    next_start = end_idx
                start_idx = next_start

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
