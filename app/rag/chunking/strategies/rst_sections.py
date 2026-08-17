"""
reStructuredText section-aware chunking strategy.

Targets .rst-like documents that use underlined/overlined section headings, e.g.:

Title
=====

Subtitle
--------

The chunker splits the document into section blocks first, then applies a
fallback RecursiveCharacterTextSplitter inside each section while preserving
character offsets.
"""


import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Line:
    start: int
    end: int
    text: str
    plain: str


@dataclass(frozen=True)
class RstHeading:
    start: int
    end: int
    level: int
    title: str
    adorn: str


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    heading: RstHeading | None


_ADORN_CHARS = "=-~^\"`:.+'_*+#"
_DIRECTIVE_HINT_RE = re.compile(r"(?m)^\s*\.\.\s*(toctree|rubric|note|warning|code-block)\s*::")


def _iter_lines(text: str) -> list[_Line]:
    out: list[_Line] = []
    offset = 0
    for raw in (text or "").splitlines(keepends=True):
        start = offset
        end = start + len(raw)
        offset = end
        plain = raw.rstrip("\r\n")
        out.append(_Line(start=start, end=end, text=raw, plain=plain))
    if not out and text:
        out.append(_Line(start=0, end=len(text), text=text, plain=text))
    return out


def _is_adornment(plain: str) -> str | None:
    s = (plain or "").strip()
    if len(s) < 3:
        return None
    ch = s[0]
    if ch not in _ADORN_CHARS:
        return None
    if any(c != ch for c in s):
        return None
    return ch


def _level_for_adorn(ch: str) -> int:
    try:
        return _ADORN_CHARS.index(ch) + 1
    except ValueError:
        return 10


def _iter_headings(text: str) -> list[RstHeading]:
    lines = _iter_lines(text)
    headings: list[RstHeading] = []
    i = 0
    while i < len(lines):
        ln = lines[i]

        # Overline + title + underline
        ch_over = _is_adornment(ln.plain)
        if ch_over and i + 2 < len(lines):
            title_ln = lines[i + 1]
            under_ln = lines[i + 2]
            ch_under = _is_adornment(under_ln.plain)
            title = title_ln.plain.strip()
            if title and ch_under == ch_over and len(under_ln.plain.strip()) >= len(title):
                headings.append(
                    RstHeading(
                        start=ln.start,
                        end=under_ln.end,
                        level=_level_for_adorn(ch_over),
                        title=title,
                        adorn=ch_over,
                    )
                )
                i += 3
                continue

        # Title + underline
        title = ln.plain.strip()
        if title and i + 1 < len(lines):
            under_ln = lines[i + 1]
            ch_under = _is_adornment(under_ln.plain)
            if ch_under and len(under_ln.plain.strip()) >= len(title):
                headings.append(
                    RstHeading(
                        start=ln.start,
                        end=under_ln.end,
                        level=_level_for_adorn(ch_under),
                        title=title,
                        adorn=ch_under,
                    )
                )
                i += 2
                continue

        i += 1

    deduped: list[RstHeading] = []
    last_start = -1
    for h in headings:
        if h.start == last_start:
            continue
        deduped.append(h)
        last_start = h.start
    return deduped


def _build_sections(text: str, headings: list[RstHeading]) -> list[_Section]:
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


def looks_like_rst_sections(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    headings = _iter_headings(text)
    if len(headings) >= 2:
        return True
    if len(headings) == 1 and _DIRECTIVE_HINT_RE.search(text):
        return True
    return False


class RSTSectionsChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ". ", "。", "！", "？", " ", ""],
            length_function=len,
            add_start_index=True,
        )

    def _append_section_chunks(
        self,
        out: list[Document],
        *,
        section: _Section,
        section_text: str,
        base_meta: dict[str, Any],
        path: list[str],
    ) -> None:
        path_str = " / ".join(path) if path else None
        split_docs = self._fallback_splitter.create_documents(texts=[section_text], metadatas=[base_meta])
        for sd in split_docs:
            local_start = sd.metadata.pop("start_index", None) or 0
            abs_start = section.start + int(local_start)
            abs_end = abs_start + len(sd.page_content)

            meta: dict[str, Any] = dict(base_meta)
            meta.update(sd.metadata or {})
            meta["chunk_strategy"] = "rst_sections"
            meta["start_char"] = abs_start
            meta["end_char"] = abs_end
            meta.setdefault("doc_type_kwd", "rst")

            if section.heading is not None:
                meta["rst_heading"] = section.heading.title
                meta["rst_level"] = int(section.heading.level)
                meta["rst_adorn"] = section.heading.adorn
            if path:
                meta["rst_path"] = path
            if path_str:
                meta["rst_path_str"] = path_str

            out.append(Document(page_content=sd.page_content, metadata=meta))

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

                if section.heading is not None:
                    _update_heading_stack(
                        heading_stack,
                        level=section.heading.level,
                        heading_text=section.heading.title,
                    )

                self._append_section_chunks(
                    out,
                    section=section,
                    section_text=sec_text,
                    base_meta=base_meta,
                    path=list(heading_stack),
                )

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
