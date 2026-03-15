"""
Org-mode section-aware chunking strategy.

Targets Emacs Org files with headings like:
- * Heading
- ** Subheading

The chunker splits the document into heading blocks first, then applies a
fallback RecursiveCharacterTextSplitter while preserving character offsets.
"""

from __future__ import annotations

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


@dataclass(frozen=True)
class OrgHeading:
    start: int
    end: int
    level: int
    title: str


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    heading: OrgHeading | None


_HEADING_RE = re.compile(r"^\s*(?P<stars>\*{1,12})\s+(?P<title>.+?)\s*$")
_FILE_KWD_RE = re.compile(r"(?mi)^\s*#\+(title|author|date|options|startup):")
_TAGS_RE = re.compile(r"\s+:[A-Za-z0-9_@#%:.-]+:\s*$")
_TODO_RE = re.compile(r"^(TODO|DONE|NEXT|WAIT|CANCELLED)\s+(?P<rest>.*)$", re.IGNORECASE)


def _iter_lines(text: str) -> list[_Line]:
    out: list[_Line] = []
    offset = 0
    for raw in (text or "").splitlines(keepends=True):
        start = offset
        end = start + len(raw)
        offset = end
        out.append(_Line(start=start, end=end, text=raw))
    if not out and text:
        out.append(_Line(start=0, end=len(text), text=text))
    return out


def _clean_title(raw: str) -> str:
    s = (raw or "").strip()
    s = _TAGS_RE.sub("", s).strip()
    m = _TODO_RE.match(s)
    if m:
        s = (m.group("rest") or "").strip()
    return s


def _iter_headings(text: str) -> list[OrgHeading]:
    headings: list[OrgHeading] = []
    for ln in _iter_lines(text):
        m = _HEADING_RE.match(ln.text.rstrip("\r\n"))
        if not m:
            continue
        level = len(m.group("stars") or "")
        title = _clean_title(m.group("title") or "")
        if not title:
            continue
        headings.append(
            OrgHeading(
                start=ln.start,
                end=ln.end,
                level=max(1, min(10, int(level))),
                title=title,
            )
        )
    deduped: list[OrgHeading] = []
    last_start = -1
    for h in headings:
        if h.start == last_start:
            continue
        deduped.append(h)
        last_start = h.start
    return deduped


def _build_sections(text: str, headings: list[OrgHeading]) -> list[_Section]:
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


def looks_like_orgmode(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    headings = _iter_headings(text)
    if len(headings) >= 2:
        return True
    if len(headings) == 1 and _FILE_KWD_RE.search(text):
        return True
    return False


class OrgModeSectionsChunker(BaseChunker):
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
                    meta["chunk_strategy"] = "orgmode_sections"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "org")

                    if section.heading is not None:
                        meta["org_heading"] = section.heading.title
                        meta["org_level"] = int(section.heading.level)
                    if path:
                        meta["org_path"] = path
                    if path_str:
                        meta["org_path_str"] = path_str

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

