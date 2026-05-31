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

from __future__ import annotations

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

        # Ignore headings inside fenced code blocks (``` or ~~~).
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif fence_marker == marker:
                in_fence = False
                fence_marker = None
            continue

        if in_fence:
            continue

        parsed = parse_markdown_hash_heading(stripped)
        if parsed is None:
            continue
        level, title = parsed
        if not title:
            continue

        headings.append(
            MarkdownHeading(
                start=line_start,
                end=line_start + len(raw_line),
                title=title,
                level=int(level),
            )
        )

    # De-duplicate headings that start at the same position (best-effort).
    deduped: list[MarkdownHeading] = []
    last_start = -1
    for h in headings:
        if h.start == last_start:
            continue
        deduped.append(h)
        last_start = h.start
    return deduped


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
                    _update_heading_stack(heading_stack, level=sec_heading.level, title=sec_heading.title)

                outline_path = list(heading_stack)
                outline_path_str = " / ".join(outline_path) if outline_path else None

                # Always go through the fallback splitter so chunk_size/overlap are respected.
                split_docs = self._fallback_splitter.create_documents(texts=[sec_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None)
                    if local_start is None:
                        local_start = 0
                    abs_start = section.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "markdown_outline"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end

                    if sec_heading is not None:
                        meta["md_heading"] = sec_heading.title
                        meta["md_level"] = int(sec_heading.level)
                    if outline_path:
                        meta["outline_path"] = outline_path
                    if outline_path_str:
                        meta["outline_path_str"] = outline_path_str
                        meta.setdefault("header_path", outline_path_str)

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        # Stable chunk_index.
        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
