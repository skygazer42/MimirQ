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

from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.utils.heading_parsing import parse_cn_prefixed_heading


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
    heading: OutlineHeading | None


_CN_NUMERAL_CHARS = set("一二三四五六七八九十百千")
_CN_PAREN_NUM_CHARS = set("0123456789一二三四五六七八九十")


def _classify_outline_heading(line: str) -> int | None:
    if (lv := _parse_numeric_heading_level(line)) is not None:
        return int(lv)
    if parse_cn_prefixed_heading(line, suffixes="章节篇回") is not None:
        return 1
    if _looks_like_cn_num_heading(line):
        return 1
    if _looks_like_cn_paren_heading(line):
        return 2
    if _looks_like_en_chapter_heading(line):
        return 1
    return None


def _append_outline_chunks(
    *,
    out: list[Document],
    splitter: RecursiveCharacterTextSplitter,
    section_text: str,
    section_start: int,
    base_meta: dict[str, Any],
    heading: OutlineHeading | None,
    header_path: list[str],
    header_path_str: str | None,
) -> None:
    split_docs = splitter.create_documents(
        texts=[section_text],
        metadatas=[base_meta],
    )
    for sd in split_docs:
        local_start = sd.metadata.pop("start_index", None)
        if local_start is None:
            local_start = 0
        abs_start = section_start + int(local_start)
        abs_end = abs_start + len(sd.page_content)

        meta: dict[str, Any] = dict(base_meta)
        meta.update(sd.metadata or {})
        meta["chunk_strategy"] = "outline"
        meta["start_char"] = abs_start
        meta["end_char"] = abs_end

        if heading is not None:
            meta["outline_heading"] = heading.text
            meta["outline_level"] = int(heading.level)
        if header_path:
            meta["outline_path"] = header_path
        if header_path_str:
            meta["outline_path_str"] = header_path_str
            meta.setdefault("header_path", header_path_str)

        out.append(Document(page_content=sd.page_content, metadata=meta))


def _parse_numeric_heading_level(line: str) -> int | None:
    """
    Parse headings like:
      1. Title
      1.1 Title
      1.1.1 Title
    Returns the heading level (number of segments) if it looks like a heading.
    """
    s = (line or "").strip()
    if not s:
        return None

    i = 0
    n = len(s)

    segs = 0
    while segs < 7:
        count = 0
        while i < n and count < 3 and s[i].isdigit():
            i += 1
            count += 1
        if count == 0:
            return None
        segs += 1

        # Continue with another segment only if '.' is followed by a digit.
        if i + 1 < n and s[i] == "." and s[i + 1].isdigit():
            i += 1
            continue
        break

    # Optional delimiter after the number ('.', '、', ')', ']').
    while i < n and s[i].isspace():
        i += 1
    if i < n and s[i] in (".", "、", ")", "]"):
        i += 1
        while i < n and s[i].isspace():
            i += 1

    title = s[i:].strip()
    if not title:
        return None
    return int(segs)


def _looks_like_cn_num_heading(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return False
    i = 0
    n = len(s)
    while i < n and s[i] in _CN_NUMERAL_CHARS:
        i += 1
    if i == 0:
        return False
    while i < n and s[i].isspace():
        i += 1
    if i >= n or s[i] not in ("、", "."):
        return False
    i += 1
    while i < n and s[i].isspace():
        i += 1
    return bool(s[i:].strip())


def _looks_like_cn_paren_heading(line: str) -> bool:
    s = (line or "").strip()
    if not s or s[0] not in ("（", "("):
        return False
    i = 1
    n = len(s)
    while i < n and s[i].isspace():
        i += 1
    start = i
    while i < n and s[i] in _CN_PAREN_NUM_CHARS:
        i += 1
    if i == start:
        return False
    while i < n and s[i].isspace():
        i += 1
    if i >= n or s[i] not in ("）", ")"):
        return False
    i += 1
    while i < n and s[i].isspace():
        i += 1
    return bool(s[i:].strip())


def _looks_like_en_chapter_heading(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return False
    low = s.lower()
    if not low.startswith("chapter") or (len(low) > 7 and not low[7].isspace()):
        return False
    i = 7
    n = len(s)
    while i < n and s[i].isspace():
        i += 1
    start = i
    while i < n and i - start < 3 and s[i].isdigit():
        i += 1
    if i == start:
        return False
    if i < n and (s[i].isalnum() or s[i] == "_"):
        return False
    if i + 1 < n and s[i] == "." and s[i + 1].isdigit():
        return False
    return True


def _iter_headings(text: str) -> list[OutlineHeading]:
    headings: list[OutlineHeading] = []
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

        level = _classify_outline_heading(line)
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
    deduped: list[OutlineHeading] = []
    last_start = -1
    for h in headings:
        if h.start == last_start:
            continue
        deduped.append(h)
        last_start = h.start
    return deduped


def _build_sections(text: str, headings: list[OutlineHeading]) -> list[_Section]:
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


def _update_heading_stack(stack: list[str], *, level: int, heading_text: str) -> None:
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
                    _update_heading_stack(heading_stack, level=sec_heading.level, heading_text=sec_heading.text)

                header_path = list(heading_stack)
                header_path_str = " / ".join(header_path) if header_path else None

                _append_outline_chunks(
                    out=out,
                    splitter=self._fallback_splitter,
                    section_text=sec_text,
                    section_start=section.start,
                    base_meta=base_meta,
                    heading=sec_heading,
                    header_path=header_path,
                    header_path_str=header_path_str,
                )

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
