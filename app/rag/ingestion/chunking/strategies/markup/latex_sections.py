"""
LaTeX section-aware chunking strategy.

Targets LaTeX documents with structural commands like:
- \\chapter{...}
- \\section{...}
- \\subsection{...}

The chunker splits the document into section blocks first, then applies a
fallback RecursiveCharacterTextSplitter inside each block while preserving
character offsets.
"""

import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.ingestion.chunking.base import BaseChunker
from app.rag.ingestion.chunking.strategies.markup import _update_heading_path
from app.rag.ingestion.chunking.utils.source_lines import apply_splitter_span


@dataclass(frozen=True)
class LatexHeading:
    start: int
    end: int
    level: int
    cmd: str
    title: str


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    heading: LatexHeading | None


_CMD_RE = re.compile(
    r"(?m)^[ \t]*\\(?P<cmd>part|chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?\s*"
    r"(?:\[[^\]]*\]\s*)?\{"
)

_CMD_LEVEL = {
    "part": 1,
    "chapter": 2,
    "section": 3,
    "subsection": 4,
    "subsubsection": 5,
    "paragraph": 6,
    "subparagraph": 7,
}


def _find_title_end(text: str, start: int) -> int | None:
    depth = 1
    escaped = False
    in_comment = False
    for index in range(start, len(text)):
        char = text[index]
        if in_comment:
            if char in "\r\n":
                in_comment = False
        elif escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "%":
            in_comment = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _iter_headings(text: str) -> list[LatexHeading]:
    if not text:
        return []

    headings: list[LatexHeading] = []
    for m in _CMD_RE.finditer(text):
        title_end = _find_title_end(text, m.end())
        if title_end is None:
            continue
        cmd = m.group("cmd")
        title = text[m.end() : title_end].strip()
        level = _CMD_LEVEL[cmd]
        headings.append(
            LatexHeading(
                start=m.start(),
                end=title_end + 1,
                level=level,
                cmd=cmd,
                title=title or cmd,
            )
        )

    return headings


def _build_sections(text: str, headings: list[LatexHeading]) -> list[_Section]:
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


def looks_like_latex_sections(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    headings = _iter_headings(text)
    if len(headings) >= 2:
        return True
    lowered = (text).lower()
    if len(headings) == 1 and ("\\documentclass" in lowered or "\\begin{document}" in lowered):
        return True
    return False


class LatexSectionsChunker(BaseChunker):
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
            local_start = sd.metadata.pop("start_index", None)

            meta: dict[str, Any] = dict(base_meta)
            meta.update(sd.metadata)
            meta["chunk_strategy"] = "latex_sections"
            apply_splitter_span(meta, start_index=local_start, content=sd.page_content, base_offset=section.start)
            meta.setdefault("doc_type_kwd", "latex")

            if section.heading is not None:
                meta["latex_heading"] = section.heading.title
                meta["latex_level"] = section.heading.level
                meta["latex_cmd"] = section.heading.cmd
            if path:
                meta["latex_path"] = path
            if path_str:
                meta["latex_path_str"] = path_str

            out.append(Document(page_content=sd.page_content, metadata=meta))

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content
            base_meta = dict(doc.metadata)
            if not text.strip():
                continue

            headings = _iter_headings(text)
            sections = _build_sections(text, headings)

            heading_stack: list[tuple[int, str]] = []
            for section in sections:
                sec_text = text[section.start : section.end]
                if not sec_text.strip():
                    continue

                if section.heading is not None:
                    _update_heading_path(
                        heading_stack,
                        level=section.heading.level,
                        heading_text=section.heading.title,
                    )

                self._append_section_chunks(
                    out,
                    section=section,
                    section_text=sec_text,
                    base_meta=base_meta,
                    path=[title for _, title in heading_stack],
                )

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata)
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
