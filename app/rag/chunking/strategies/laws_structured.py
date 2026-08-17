"""
Laws / contract structured chunking strategy.

Targets legal-style documents with explicit clause markers, e.g.:
- 第1章 / 第2节 / 第3条 / （一）...
- Article 1 / Section 2 ...

The chunker splits by detected legal headings first, then applies a fallback
RecursiveCharacterTextSplitter inside each section to respect chunk_size and
chunk_overlap while preserving character offsets.
"""


from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.utils.heading_parsing import parse_cn_clause_marker, parse_cn_prefixed_heading


@dataclass(frozen=True)
class LawHeading:
    start: int
    end: int
    text: str
    level: int
    kind: str  # chapter|section|article|clause
    number: str | None = None


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    heading: LawHeading | None


def _skip_spaces(text: str, idx: int) -> int:
    while idx < len(text) and text[idx].isspace():
        idx += 1
    return idx


def _parse_digit_segment(text: str, idx: int, *, max_digits: int = 4) -> int:
    start = idx
    while idx < len(text) and idx - start < max_digits and text[idx].isdigit():
        idx += 1
    return idx


def _parse_dotted_number(text: str, idx: int, *, max_segments: int) -> tuple[int, int] | None:
    start = idx
    idx = _parse_digit_segment(text, idx)
    if idx == start:
        return None

    segments = 1
    while segments < max_segments and idx < len(text) and text[idx] == ".":
        next_idx = _parse_digit_segment(text, idx + 1)
        if next_idx == idx + 1:
            break
        idx = next_idx
        segments += 1
    return start, idx


def _has_heading_boundary(text: str, idx: int) -> bool:
    if idx >= len(text):
        return True
    if text[idx].isalnum() or text[idx] == "_":
        return False
    return not (idx + 1 < len(text) and text[idx] == "." and text[idx + 1].isdigit())


def _parse_en_prefixed_heading(line: str, *, prefix: str, max_segments: int) -> str | None:
    s = (line or "").strip()
    if not s:
        return None
    low = s.lower()
    prefix_len = len(prefix)
    if not low.startswith(prefix) or (len(low) > prefix_len and not low[prefix_len].isspace()):
        return None

    number_start = _skip_spaces(s, prefix_len)
    bounds = _parse_dotted_number(s, number_start, max_segments=max_segments)
    if bounds is None:
        return None
    start, end = bounds
    if not _has_heading_boundary(s, end):
        return None
    return s[start:end]


def _parse_en_article_heading(line: str) -> str | None:
    return _parse_en_prefixed_heading(line, prefix="article", max_segments=1)


def _parse_en_section_heading(line: str) -> str | None:
    return _parse_en_prefixed_heading(line, prefix="section", max_segments=4)


def _heading_match(line: str) -> tuple[str, int, str] | None:
    candidates = (
        ("chapter", 1, parse_cn_prefixed_heading(line, suffixes="章")),
        ("section", 2, parse_cn_prefixed_heading(line, suffixes="节")),
        ("article", 3, parse_cn_prefixed_heading(line, suffixes="条")),
        ("clause", 4, parse_cn_clause_marker(line)),
        ("article", 3, _parse_en_article_heading(line)),
        ("section", 2, _parse_en_section_heading(line)),
    )
    for kind, level, number in candidates:
        if number is not None:
            return kind, level, number
    return None


def _parse_heading(raw_line: str, *, line_start: int) -> LawHeading | None:
    line = raw_line.strip()
    if not line or len(line) > 200:
        return None

    match = _heading_match(line)
    if match is None:
        return None

    kind, level, number = match
    return LawHeading(
        start=line_start,
        end=line_start + len(raw_line),
        text=line,
        level=level,
        kind=kind,
        number=number,
    )


def _dedupe_headings(headings: list[LawHeading]) -> list[LawHeading]:
    deduped: list[LawHeading] = []
    last_start = -1
    for heading in headings:
        if heading.start == last_start:
            continue
        deduped.append(heading)
        last_start = heading.start
    return deduped


def _iter_headings(text: str) -> list[LawHeading]:
    if not text:
        return []

    headings: list[LawHeading] = []
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)
        heading = _parse_heading(raw_line, line_start=line_start)
        if heading is not None:
            headings.append(heading)
    return _dedupe_headings(headings)


def _build_sections(text: str, headings: list[LawHeading]) -> list[_Section]:
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


def _update_heading_stack(stack: list[LawHeading], *, heading: LawHeading) -> None:
    # Keep stack ordered by level.
    while stack and stack[-1].level >= heading.level:
        stack.pop()
    stack.append(heading)


def looks_like_laws(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    headings = _iter_headings(text)
    if not headings:
        return False
    articles = [h for h in headings if h.kind == "article"]
    # Avoid matching generic outlines; require multiple "articles".
    return len(articles) >= 2


class LawsStructuredChunker(BaseChunker):
    """
    Chunker optimized for legal-style documents (laws, policies, contracts).
    """

    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "；", "，", ". ", "!", "?", " ", ""],
            length_function=len,
            add_start_index=True,
        )

    def _section_path(self, stack: list[LawHeading], heading: LawHeading | None) -> tuple[list[str], str | None]:
        if heading is not None:
            _update_heading_stack(stack, heading=heading)
        path = [item.text for item in stack]
        return path, " / ".join(path) if path else None

    def _build_chunk_metadata(
        self,
        base_meta: dict[str, Any],
        *,
        abs_start: int,
        abs_end: int,
        heading: LawHeading | None,
        path: list[str],
        path_str: str | None,
    ) -> dict[str, Any]:
        meta: dict[str, Any] = dict(base_meta)
        meta["chunk_strategy"] = "laws_structured"
        meta["start_char"] = abs_start
        meta["end_char"] = abs_end
        if heading is not None:
            meta["law_heading"] = heading.text
            meta["law_level"] = int(heading.level)
            meta["law_kind"] = heading.kind
            if heading.number:
                meta["law_number"] = heading.number
            if heading.kind == "article":
                meta["law_article"] = heading.text
        if path:
            meta["law_path"] = path
        if path_str:
            meta["law_path_str"] = path_str
        return meta

    def _split_section_documents(
        self,
        section: _Section,
        section_text: str,
        base_meta: dict[str, Any],
        path: list[str],
        path_str: str | None,
    ) -> list[Document]:
        out: list[Document] = []
        split_docs = self._fallback_splitter.create_documents(texts=[section_text], metadatas=[base_meta])
        for split_doc in split_docs:
            local_start = split_doc.metadata.pop("start_index", None) or 0
            abs_start = section.start + int(local_start)
            abs_end = abs_start + len(split_doc.page_content)
            meta = self._build_chunk_metadata(
                base_meta,
                abs_start=abs_start,
                abs_end=abs_end,
                heading=section.heading,
                path=path,
                path_str=path_str,
            )
            meta.update(split_doc.metadata or {})
            out.append(Document(page_content=split_doc.page_content, metadata=meta))
        return out

    def _split_document(self, doc: Document) -> list[Document]:
        text = doc.page_content or ""
        if not text.strip():
            return []

        base_meta = dict(doc.metadata or {})
        sections = _build_sections(text, _iter_headings(text))
        stack: list[LawHeading] = []
        out: list[Document] = []
        for section in sections:
            section_text = text[section.start : section.end]
            if not section_text.strip():
                continue
            path, path_str = self._section_path(stack, section.heading)
            out.extend(self._split_section_documents(section, section_text, base_meta, path, path_str))
        return out

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            out.extend(self._split_document(doc))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
