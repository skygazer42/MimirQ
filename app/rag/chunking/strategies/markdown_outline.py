"""
Markdown outline-aware chunking strategy.

Splits markdown documents by heading hierarchy (#, ##, ###, ...) and preserves
the current heading path in metadata for better retrieval and citation context.

The chunker:
1) Detects markdown headings outside fenced code blocks
2) Splits into sections by heading boundaries
3) Applies a fallback RecursiveCharacterTextSplitter inside each section to
   respect chunk_size/chunk_overlap while preserving absolute offsets.
"""

from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.utils.heading_parsing import parse_markdown_hash_heading


@dataclass(frozen=True)
class MarkdownHeading:
    start: int
    end: int
    title: str
    level: int


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    heading: MarkdownHeading | None


def _advance_fence(
    stripped: str,
    *,
    in_fence: bool,
    fence_marker: str | None,
) -> tuple[bool, bool, str | None]:
    if not stripped.startswith(("```", "~~~")):
        return False, in_fence, fence_marker
    marker = stripped[:3]
    if not in_fence:
        return True, True, marker
    if fence_marker == marker:
        return True, False, None
    return True, in_fence, fence_marker


def _heading_from_line(raw_line: str, *, line_start: int) -> MarkdownHeading | None:
    parsed = parse_markdown_hash_heading(raw_line.strip())
    if parsed is None:
        return None
    level, title = parsed
    if not title:
        return None
    return MarkdownHeading(
        start=line_start,
        end=line_start + len(raw_line),
        title=title,
        level=int(level),
    )


def _dedupe_headings(headings: list[MarkdownHeading]) -> list[MarkdownHeading]:
    deduped: list[MarkdownHeading] = []
    last_start = -1
    for heading in headings:
        if heading.start != last_start:
            deduped.append(heading)
            last_start = heading.start
    return deduped


def _iter_headings(text: str) -> list[MarkdownHeading]:
    headings: list[MarkdownHeading] = []
    if not text:
        return headings

    offset = 0
    in_fence = False
    fence_marker: str | None = None

    for raw_line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)

        stripped = raw_line.strip()
        if not stripped:
            continue

        is_fence, in_fence, fence_marker = _advance_fence(
            stripped,
            in_fence=in_fence,
            fence_marker=fence_marker,
        )
        if is_fence:
            continue
        if in_fence:
            continue
        heading = _heading_from_line(raw_line, line_start=line_start)
        if heading is not None:
            headings.append(heading)

    return _dedupe_headings(headings)


def _build_sections(text: str, headings: list[MarkdownHeading]) -> list[_Section]:
    if not headings:
        return [_Section(start=0, end=len(text), heading=None)]

    sections: list[_Section] = []

    first = headings[0]
    if first.start > 0:
        sections.append(_Section(start=0, end=first.start, heading=None))

    for idx, heading in enumerate(headings):
        start = heading.start
        end = headings[idx + 1].start if idx + 1 < len(headings) else len(text)
        sections.append(_Section(start=start, end=end, heading=heading))

    return sections


def _update_heading_stack(stack: list[str], *, level: int, title: str) -> None:
    level = max(1, int(level))
    while len(stack) >= level:
        stack.pop()
    stack.append(title)


class MarkdownOutlineChunker(BaseChunker):
    """
    Chunker optimized for markdown documents with clear heading hierarchy.
    """

    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ". ", "。", "！", "？", "! ", "? ", " ", ""],
            length_function=len,
            add_start_index=True,
        )

    @staticmethod
    def _chunk_metadata(
        *,
        base_meta: dict[str, Any],
        split_meta: dict[str, Any],
        section: _Section,
        outline_path: list[str],
        start: int,
        end: int,
    ) -> dict[str, Any]:
        meta: dict[str, Any] = dict(base_meta)
        meta.update(split_meta)
        meta.update(
            {
                "chunk_strategy": "markdown_outline",
                "start_char": start,
                "end_char": end,
            }
        )
        if section.heading is not None:
            meta["md_heading"] = section.heading.title
            meta["md_level"] = int(section.heading.level)
        if outline_path:
            outline_path_str = " / ".join(outline_path)
            meta["outline_path"] = outline_path
            meta["outline_path_str"] = outline_path_str
            meta.setdefault("header_path", outline_path_str)
        return meta

    def _append_section_chunks(
        self,
        out: list[Document],
        *,
        text: str,
        section: _Section,
        heading_stack: list[str],
        base_meta: dict[str, Any],
    ) -> None:
        section_text = text[section.start : section.end]
        if not section_text.strip():
            return
        if section.heading is not None:
            _update_heading_stack(
                heading_stack,
                level=section.heading.level,
                title=section.heading.title,
            )
        outline_path = list(heading_stack)
        split_docs = self._fallback_splitter.create_documents(
            texts=[section_text],
            metadatas=[base_meta],
        )
        for split_doc in split_docs:
            local_start = split_doc.metadata.pop("start_index", None)
            absolute_start = section.start + int(local_start or 0)
            meta = self._chunk_metadata(
                base_meta=base_meta,
                split_meta=dict(split_doc.metadata or {}),
                section=section,
                outline_path=outline_path,
                start=absolute_start,
                end=absolute_start + len(split_doc.page_content),
            )
            out.append(Document(page_content=split_doc.page_content, metadata=meta))

    def _split_document(self, doc: Document, out: list[Document]) -> None:
        text = doc.page_content or ""
        if not text.strip():
            return
        base_meta = dict(doc.metadata or {})
        heading_stack: list[str] = []
        for section in _build_sections(text, _iter_headings(text)):
            self._append_section_chunks(
                out,
                text=text,
                section=section,
                heading_stack=heading_stack,
                base_meta=base_meta,
            )

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []
        for doc in documents:
            self._split_document(doc, out)
        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta
        return out
