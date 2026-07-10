"""
MediaWiki section-aware chunking strategy.

Targets wiki markup with headings like:
== Heading ==
=== Subheading ===

The chunker splits the document into heading sections while preserving
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


@dataclass(frozen=True)
class WikiHeading:
    start: int
    end: int
    level: int
    title: str


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    heading: WikiHeading | None


_WIKI_HINT_RE = re.compile(r"(\[\[[^\]]+\]\])|(\{\{[^}]+\}\})")


def _parse_wiki_heading(line: str) -> tuple[int, str] | None:
    """
    Parse a MediaWiki heading like:
      == Heading ==
      === Subheading ===

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    raw = str(line or "").rstrip("\r\n")
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None
    i = 0
    while i < len(s) and s[i] == "=":
        i += 1
    if i < 2 or i > 6:
        return None
    j = len(s)
    while j > 0 and s[j - 1] == "=":
        j -= 1
    if (len(s) - j) != i:
        return None
    title = s[i:j].strip()
    if not title:
        return None
    level = max(1, min(6, int(i) - 1))
    return level, title


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


def _iter_headings(text: str) -> list[WikiHeading]:
    headings: list[WikiHeading] = []
    for ln in _iter_lines(text):
        parsed = _parse_wiki_heading(ln.text)
        if not parsed:
            continue
        level, title = parsed
        headings.append(
            WikiHeading(
                start=ln.start,
                end=ln.end,
                level=int(level),
                title=title,
            )
        )
    deduped: list[WikiHeading] = []
    last_start = -1
    for h in headings:
        if h.start == last_start:
            continue
        deduped.append(h)
        last_start = h.start
    return deduped


def _build_sections(text: str, headings: list[WikiHeading]) -> list[_Section]:
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


def looks_like_mediawiki(text: str) -> bool:
    if not text or len(text) < 40:
        return False
    headings = _iter_headings(text)
    if len(headings) >= 2:
        return True
    if len(headings) == 1 and _WIKI_HINT_RE.search(text):
        return True
    return False


class MediaWikiSectionsChunker(BaseChunker):
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
                    meta["chunk_strategy"] = "mediawiki_sections"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "wiki")

                    if section.heading is not None:
                        meta["wiki_heading"] = section.heading.title
                        meta["wiki_level"] = int(section.heading.level)
                    if path:
                        meta["wiki_path"] = path
                    if path_str:
                        meta["wiki_path_str"] = path_str

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
