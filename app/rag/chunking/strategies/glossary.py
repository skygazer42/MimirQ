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
import re
from typing import Any, List, Optional

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Entry:
    start: int
    end: int
    term: str


_INLINE_ENTRY_RE = re.compile(
    r"(?m)^\s*(?P<term>(?:[A-Za-z][A-Za-z0-9 _./+()-]{0,40}|[\u4e00-\u9fff]{2,20}))\s*(?:[:：]|[–—-])\s+(?P<def>.+?)\s*$"
)


def _iter_entries(text: str) -> List[_Entry]:
    if not text:
        return []

    matches = list(_INLINE_ENTRY_RE.finditer(text))
    if len(matches) < 2:
        return []

    entries: List[_Entry] = []
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)

        term = (m.group("term") or "").strip()
        if not term:
            continue
        if len(term) > 60:
            continue

        # Filter out obvious false positives (very long "term" segments).
        if term.count(" ") > 6:
            continue

        entries.append(_Entry(start=start, end=end, term=term))

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

    def split_documents(self, documents: List[Document]) -> List[Document]:
        out: List[Document] = []

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

