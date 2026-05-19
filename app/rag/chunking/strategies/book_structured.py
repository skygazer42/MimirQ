"""
Book-structured chunking strategy.

Targets book-like documents with explicit chapter/part markers, e.g.:
- Chapter 1 / CHAPTER IV / Part II / Volume 1
- 第1章 / 第三回 / 第一卷 / 第二节

The chunker splits the document into book sections first, then applies a
fallback RecursiveCharacterTextSplitter inside each section to respect the
configured chunk size/overlap while preserving positions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.utils.heading_parsing import parse_cn_prefixed_heading


@dataclass(frozen=True)
class BookHeading:
    start: int
    end: int
    text: str
    level: int
    kind: str  # volume|part|chapter|section


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    heading: BookHeading | None


_ROMAN_CHARS = set("ivxlcdm")


def _parse_en_num_simple(s: str, start: int) -> tuple[str, int] | None:
    """
    Parse either digits (1-4) or a simple roman token ([ivxlcdm]{1,10}).
    Returns (num, next_index).
    """
    n = len(s)
    i = start
    j = i
    while j < n and j - i < 4 and s[j].isdigit():
        j += 1
    if j > i:
        return s[i:j], j

    j = i
    while j < n and j - i < 10 and s[j].lower() in _ROMAN_CHARS:
        j += 1
    if j > i:
        return s[i:j], j
    return None


def _parse_en_num_section(s: str, start: int) -> tuple[str, int] | None:
    n = len(s)
    i = start

    def parse_segment(idx: int) -> int:
        seg_start = idx
        while idx < n and idx - seg_start < 4 and s[idx].isdigit():
            idx += 1
        return idx if idx > seg_start else seg_start

    i0 = i
    i = parse_segment(i)
    if i == i0:
        return None
    segs = 1
    while segs < 4 and i < n and s[i] == ".":
        nxt = parse_segment(i + 1)
        if nxt == i + 1:
            break
        i = nxt
        segs += 1
    return s[start:i], i


def _parse_en_heading(line: str) -> tuple[str, int, str] | None:
    """
    Parse book-ish headings without regex to avoid backtracking hotspots.
    Returns (kind, level, number).
    """
    s = (line or "").strip()
    if not s:
        return None
    low = s.lower()
    n = len(s)

    candidates = [
        ("volume", 1, ("volume", "vol."), _parse_en_num_simple),
        ("book", 1, ("book",), _parse_en_num_simple),
        ("part", 1, ("part",), _parse_en_num_simple),
        ("chapter", 2, ("chapter", "ch."), _parse_en_num_simple),
        ("section", 3, ("section",), _parse_en_num_section),
    ]

    for kind, level, prefixes, num_parser in candidates:
        for pref in prefixes:
            if not low.startswith(pref):
                continue
            if len(low) > len(pref) and not low[len(pref)].isspace():
                continue

            i = len(pref)
            while i < n and s[i].isspace():
                i += 1
            if i >= n:
                continue

            parsed = num_parser(s, i)
            if not parsed:
                continue
            num, j = parsed
            if j < n and (s[j].isalnum() or s[j] == "_"):
                continue
            if j + 1 < n and s[j] == "." and s[j + 1].isdigit():
                continue
            return kind, int(level), num

    return None


def _iter_headings(text: str) -> list[BookHeading]:
    headings: list[BookHeading] = []
    if not text:
        return headings

    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)

        line = raw_line.strip()
        if not line:
            continue
        if len(line) > 160:
            continue

        kind: str | None = None
        level: int | None = None
        if parse_cn_prefixed_heading(line, suffixes="卷") is not None:
            kind, level = "volume", 1
        elif parse_cn_prefixed_heading(line, suffixes="部") is not None:
            kind, level = "part", 1
        elif parse_cn_prefixed_heading(line, suffixes="章回") is not None:
            kind, level = "chapter", 2
        elif parse_cn_prefixed_heading(line, suffixes="节") is not None:
            kind, level = "section", 3
        elif (en := _parse_en_heading(line)) is not None:
            kind, level, _ = en

        if kind is None or level is None:
            continue

        headings.append(
            BookHeading(
                start=line_start,
                end=line_start + len(raw_line),
                text=line,
                level=int(level),
                kind=kind,
            )
        )

    # Best-effort de-dup.
    deduped: list[BookHeading] = []
    last_start = -1
    for h in headings:
        if h.start == last_start:
            continue
        deduped.append(h)
        last_start = h.start
    return deduped


def _build_sections(text: str, headings: list[BookHeading]) -> list[_Section]:
    if not headings:
        return [_Section(start=0, end=len(text), heading=None)]

    sections: list[_Section] = []
    first = headings[0]
    if first.start > 0:
        sections.append(_Section(start=0, end=first.start, heading=None))

    for idx, h in enumerate(headings):
        start = h.start
        end = headings[idx + 1].start if idx + 1 < len(headings) else len(text)
        sections.append(_Section(start=start, end=end, heading=h))

    return sections


def _update_heading_stack(stack: list[str], *, level: int, heading_text: str) -> None:
    level = max(1, int(level))
    while len(stack) >= level:
        stack.pop()
    stack.append(heading_text)


def looks_like_book(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    headings = _iter_headings(text)
    if len(headings) < 2:
        return False
    chapter_like = sum(1 for h in headings if h.kind in {"chapter"} or h.level >= 2)
    return chapter_like >= 1


class BookStructuredChunker(BaseChunker):
    """
    Chunker optimized for book-like chapter/part structure.
    """

    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ". ", "。", "，", "!", "?", " ", ""],
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

            headings = _iter_headings(text)
            sections = _build_sections(text, headings)

            heading_stack: list[str] = []

            for section in sections:
                sec_text = text[section.start : section.end]
                if not sec_text.strip():
                    continue

                sec_heading = section.heading
                if sec_heading is not None:
                    _update_heading_stack(
                        heading_stack,
                        level=sec_heading.level,
                        heading_text=sec_heading.text,
                    )

                path = list(heading_stack)
                path_str = " / ".join(path) if path else None

                split_docs = self._fallback_splitter.create_documents(
                    texts=[sec_text],
                    metadatas=[base_meta],
                )
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = section.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "book_structured"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end

                    if sec_heading is not None:
                        meta["book_heading"] = sec_heading.text
                        meta["book_level"] = int(sec_heading.level)
                        meta["book_kind"] = sec_heading.kind
                    if path:
                        meta["book_path"] = path
                    if path_str:
                        meta["book_path_str"] = path_str

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
