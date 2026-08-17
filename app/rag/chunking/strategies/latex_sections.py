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

from app.rag.chunking.base import BaseChunker


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
    r"(?:\[[^\]]*\]\s*)?\{(?P<title>[^\}]*)\}"
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


def _iter_headings(text: str) -> list[LatexHeading]:
    if not text:
        return []

    headings: list[LatexHeading] = []
    for m in _CMD_RE.finditer(text):
        cmd = (m.group("cmd") or "").strip().lower()
        title = (m.group("title") or "").strip()
        if not cmd:
            continue
        level = int(_CMD_LEVEL.get(cmd, 9))
        headings.append(
            LatexHeading(
                start=m.start(),
                end=m.end(),
                level=level,
                cmd=cmd,
                title=title or cmd,
            )
        )

    deduped: list[LatexHeading] = []
    last_start = -1
    for h in headings:
        if h.start == last_start:
            continue
        deduped.append(h)
        last_start = h.start
    return deduped


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


def _update_heading_stack(stack: list[str], *, level: int, heading_text: str) -> None:
    level = max(1, int(level))
    while len(stack) >= level:
        stack.pop()
    stack.append(heading_text)


def looks_like_latex_sections(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    headings = _iter_headings(text)
    if len(headings) >= 2:
        return True
    lowered = (text or "").lower()
    if len(headings) == 1 and ("\\documentclass" in lowered or "\\begin{document}" in lowered):
        return True
    return False


class LatexSectionsChunker(BaseChunker):
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
            meta["chunk_strategy"] = "latex_sections"
            meta["start_char"] = abs_start
            meta["end_char"] = abs_end
            meta.setdefault("doc_type_kwd", "latex")

            if section.heading is not None:
                meta["latex_heading"] = section.heading.title
                meta["latex_level"] = int(section.heading.level)
                meta["latex_cmd"] = section.heading.cmd
            if path:
                meta["latex_path"] = path
            if path_str:
                meta["latex_path_str"] = path_str

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
