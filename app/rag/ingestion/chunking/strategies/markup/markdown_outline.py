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

from app.rag.ingestion.chunking.base import BaseChunker
from app.rag.ingestion.chunking.strategies.markup import _update_heading_path
from app.rag.ingestion.chunking.strategies.markup.markdown import _iter_markdown_heading_lines
from app.rag.ingestion.chunking.utils.source_lines import apply_splitter_span


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
    return [
        MarkdownHeading(start=start, end=start + len(line), title=title, level=level)
        for start, line, level, title in _iter_markdown_heading_lines(text)
    ]


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


class MarkdownOutlineChunker(BaseChunker):
    """
    Chunker optimized for markdown documents with clear heading hierarchy.
    """

    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
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
        start_index: int | None,
        content: str,
    ) -> dict[str, Any]:
        meta: dict[str, Any] = dict(base_meta)
        meta.update(split_meta)
        meta["chunk_strategy"] = "markdown_outline"
        apply_splitter_span(meta, start_index=start_index, content=content, base_offset=section.start)
        if section.heading is not None:
            meta["md_heading"] = section.heading.title
            meta["md_level"] = section.heading.level
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
        heading_stack: list[tuple[int, str]],
        base_meta: dict[str, Any],
    ) -> None:
        section_text = text[section.start : section.end]
        if not section_text.strip():
            return
        if section.heading is not None:
            _update_heading_path(
                heading_stack,
                level=section.heading.level,
                heading_text=section.heading.title,
            )
        outline_path = [title for _, title in heading_stack]
        split_docs = self._fallback_splitter.create_documents(
            texts=[section_text],
            metadatas=[base_meta],
        )
        for split_doc in split_docs:
            local_start = split_doc.metadata.pop("start_index", None)
            meta = self._chunk_metadata(
                base_meta=base_meta,
                split_meta=dict(split_doc.metadata),
                section=section,
                outline_path=outline_path,
                start_index=local_start,
                content=split_doc.page_content,
            )
            out.append(Document(page_content=split_doc.page_content, metadata=meta))

    def _split_document(self, doc: Document, out: list[Document]) -> None:
        text = doc.page_content
        if not text.strip():
            return
        base_meta = dict(doc.metadata)
        heading_stack: list[tuple[int, str]] = []
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
            meta = dict(chunk.metadata)
            meta["chunk_index"] = idx
            chunk.metadata = meta
        return out
