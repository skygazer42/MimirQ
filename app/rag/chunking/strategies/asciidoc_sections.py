"""
AsciiDoc section-aware chunking strategy.

Targets AsciiDoc-like documents with headings such as:
- = Title
- == Section
- === Subsection

The chunker splits by heading blocks and preserves character offsets.
"""

from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.utils.heading_parsing import update_heading_stack as _update_heading_stack
from app.rag.chunking.utils.source_lines import iter_source_lines as _iter_lines


@dataclass(frozen=True)
class AsciidocHeading:
    start: int
    end: int
    level: int
    title: str


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    heading: AsciidocHeading | None


def _parse_asciidoc_heading(line: str) -> tuple[int, str] | None:
    """
    Parse an AsciiDoc heading line like:
      = Title
      == Section

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    raw = line.rstrip("\r\n")
    if not raw:
        return None
    s = raw.lstrip()
    if not s.startswith("="):
        return None

    i = 0
    n = len(s)
    while i < n and i < 6 and s[i] == "=":
        i += 1
    # Reject >6 leading '='.
    if i < n and s[i] == "=":
        return None
    # Require at least one whitespace after the marker run.
    if i >= n or not s[i].isspace():
        return None
    j = i
    while j < n and s[j].isspace():
        j += 1
    title = s[j:].strip()
    if not title:
        return None
    return i, title


def _iter_headings(text: str) -> list[AsciidocHeading]:
    headings: list[AsciidocHeading] = []
    for ln in _iter_lines(text):
        parsed = _parse_asciidoc_heading(ln.plain)
        if not parsed:
            continue
        level, title = parsed
        headings.append(
            AsciidocHeading(
                start=ln.start,
                end=ln.end,
                level=level,
                title=title,
            )
        )
    return headings


def _build_sections(text: str, headings: list[AsciidocHeading]) -> list[_Section]:
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


def looks_like_asciidoc(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    headings = _iter_headings(text)
    if len(headings) >= 2:
        return True
    lowered = (text).lower()
    if len(headings) == 1 and (":toc:" in lowered or ":doctype:" in lowered or "[source" in lowered):
        return True
    return False


class AsciiDocSectionsChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
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
            meta["chunk_strategy"] = "asciidoc_sections"
            meta["start_char"] = abs_start
            meta["end_char"] = abs_end
            meta.setdefault("doc_type_kwd", "asciidoc")

            if section.heading is not None:
                meta["asciidoc_heading"] = section.heading.title
                meta["asciidoc_level"] = section.heading.level
            if path:
                meta["asciidoc_path"] = path
            if path_str:
                meta["asciidoc_path_str"] = path_str

            out.append(Document(page_content=sd.page_content, metadata=meta))

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content
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
