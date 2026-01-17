"""
Outline-aware chunking strategy.

Targets documents that use numbered headings, such as:
- 1. / 1.1 / 1.1.1 ...
- 一、 / （一） ...
- 第1章 / 第三节 ...

The chunker first splits the document into outline sections, then applies a
fallback RecursiveCharacterTextSplitter inside each section to respect the
configured chunk size/overlap while preserving positions.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, List, Optional

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class OutlineHeading:
    start: int
    end: int
    text: str
    level: int


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    heading: Optional[OutlineHeading]


_RE_NUMERIC = re.compile(
    r"^(?P<num>\d{1,3}(?:\.\d{1,3}){0,6})\s*(?:[\.、)\]]\s*)?(?P<title>.+?)\s*$"
)
_RE_CN_CHAPTER = re.compile(
    r"^(?P<prefix>第[0-9一二三四五六七八九十百千]+[章节篇回])\s*(?P<title>.*?)\s*$"
)
_RE_CN_NUM = re.compile(r"^(?P<num>[一二三四五六七八九十百千]+)\s*[、\.]\s*(?P<title>.+?)\s*$")
_RE_CN_PAREN = re.compile(r"^[（(]\s*(?P<num>[0-9一二三四五六七八九十]+)\s*[）)]\s*(?P<title>.+?)\s*$")
_RE_EN_CHAPTER = re.compile(r"^(?P<prefix>chapter)\s+(?P<num>\d{1,3})\b\s*(?P<title>.*?)\s*$", re.IGNORECASE)


def _iter_headings(text: str) -> List[OutlineHeading]:
    headings: List[OutlineHeading] = []
    if not text:
        return headings

    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)

        line = raw_line.strip()
        if not line:
            continue
        # Avoid pathological headings (e.g. a whole paragraph).
        if len(line) > 160:
            continue

        level: Optional[int] = None
        if (m := _RE_NUMERIC.match(line)) is not None:
            # 1. / 1.1 / 1.1.1 -> level = segments
            level = max(1, len(m.group("num").split(".")))
        elif _RE_CN_CHAPTER.match(line):
            level = 1
        elif _RE_CN_NUM.match(line):
            level = 1
        elif _RE_CN_PAREN.match(line):
            level = 2
        elif _RE_EN_CHAPTER.match(line):
            level = 1

        if level is None:
            continue

        headings.append(
            OutlineHeading(
                start=line_start,
                end=line_start + len(raw_line),
                text=line,
                level=int(level),
            )
        )

    # De-duplicate headings that start at the same position (best-effort).
    deduped: List[OutlineHeading] = []
    last_start = -1
    for h in headings:
        if h.start == last_start:
            continue
        deduped.append(h)
        last_start = h.start
    return deduped


def _build_sections(text: str, headings: List[OutlineHeading]) -> List[_Section]:
    if not headings:
        return [_Section(start=0, end=len(text), heading=None)]

    sections: List[_Section] = []

    first = headings[0]
    if first.start > 0:
        sections.append(_Section(start=0, end=first.start, heading=None))

    for idx, heading in enumerate(headings):
        start = heading.start
        end = headings[idx + 1].start if idx + 1 < len(headings) else len(text)
        sections.append(_Section(start=start, end=end, heading=heading))

    return sections


def _update_heading_stack(stack: List[str], *, level: int, heading_text: str) -> None:
    level = max(1, int(level))
    # Ensure stack depth matches heading level.
    while len(stack) >= level:
        stack.pop()
    stack.append(heading_text)


class OutlineChunker(BaseChunker):
    """
    Chunker optimized for numbered-outline documents (manuals, policies, SOPs).
    """

    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ". ", "。", "！", "？", "!", "?", " ", ""],
            length_function=len,
            add_start_index=True,
        )

    def split_documents(self, documents: List[Document]) -> List[Document]:
        out: List[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            headings = _iter_headings(text)
            sections = _build_sections(text, headings)

            heading_stack: List[str] = []

            for section in sections:
                sec_text = text[section.start : section.end]
                if not sec_text.strip():
                    continue

                sec_heading = section.heading
                if sec_heading is not None:
                    _update_heading_stack(heading_stack, level=sec_heading.level, heading_text=sec_heading.text)

                header_path = list(heading_stack)
                header_path_str = " / ".join(header_path) if header_path else None

                # Always go through the fallback splitter so chunk_size/overlap are respected.
                split_docs = self._fallback_splitter.create_documents(
                    texts=[sec_text],
                    metadatas=[base_meta],
                )
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None)
                    if local_start is None:
                        local_start = 0
                    abs_start = section.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "outline"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end

                    if sec_heading is not None:
                        meta["outline_heading"] = sec_heading.text
                        meta["outline_level"] = int(sec_heading.level)
                    if header_path:
                        meta["outline_path"] = header_path
                    if header_path_str:
                        meta["outline_path_str"] = header_path_str

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        # Re-index chunks (stable order).
        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out


def looks_like_outline(text: str) -> bool:
    """
    Cheap heuristic for outline detection.
    """
    if not text or len(text) < 80:
        return False
    headings = _iter_headings(text)
    # Require at least 2 headings to avoid matching random list items.
    return len(headings) >= 2
