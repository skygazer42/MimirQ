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


def _parse_en_article_heading(line: str) -> str | None:
    s = (line or "").strip()
    if not s:
        return None
    low = s.lower()
    if not low.startswith("article") or (len(low) > 7 and not low[7].isspace()):
        return None

    i = 7
    n = len(s)
    while i < n and s[i].isspace():
        i += 1
    start = i
    while i < n and i - start < 4 and s[i].isdigit():
        i += 1
    if i == start:
        return None
    # Require a boundary (space/punct/end) after the number.
    if i < n and (s[i].isalnum() or s[i] == "_"):
        return None
    if i + 1 < n and s[i] == "." and s[i + 1].isdigit():
        return None
    return s[start:i]


def _parse_en_section_heading(line: str) -> str | None:
    s = (line or "").strip()
    if not s:
        return None
    low = s.lower()
    if not low.startswith("section") or (len(low) > 7 and not low[7].isspace()):
        return None

    i = 7
    n = len(s)
    while i < n and s[i].isspace():
        i += 1

    def parse_segment(idx: int) -> int:
        start = idx
        while idx < n and idx - start < 4 and s[idx].isdigit():
            idx += 1
        return idx if idx > start else start

    start = i
    i = parse_segment(i)
    if i == start:
        return None
    segs = 1
    while segs < 4 and i < n and s[i] == ".":
        nxt = parse_segment(i + 1)
        if nxt == i + 1:
            break
        i = nxt
        segs += 1

    if i < n and (s[i].isalnum() or s[i] == "_"):
        return None
    if i + 1 < n and s[i] == "." and s[i + 1].isdigit():
        return None
    return s[start:i]


def _iter_headings(text: str) -> list[LawHeading]:
    headings: list[LawHeading] = []
    if not text:
        return headings

    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)

        line = raw_line.strip()
        if not line:
            continue
        if len(line) > 200:
            continue

        kind: str | None = None
        level: int | None = None
        num: str | None = None

        if (prefix := parse_cn_prefixed_heading(line, suffixes="章")) is not None:
            kind, level, num = "chapter", 1, prefix
        elif (prefix := parse_cn_prefixed_heading(line, suffixes="节")) is not None:
            kind, level, num = "section", 2, prefix
        elif (prefix := parse_cn_prefixed_heading(line, suffixes="条")) is not None:
            kind, level, num = "article", 3, prefix
        elif (prefix := parse_cn_clause_marker(line)) is not None:
            kind, level, num = "clause", 4, prefix
        elif (en_num := _parse_en_article_heading(line)) is not None:
            kind, level, num = "article", 3, en_num
        elif (en_num := _parse_en_section_heading(line)) is not None:
            kind, level, num = "section", 2, en_num

        if kind is None or level is None:
            continue

        headings.append(
            LawHeading(
                start=line_start,
                end=line_start + len(raw_line),
                text=line,
                level=int(level),
                kind=kind,
                number=num,
            )
        )

    # Best-effort de-dup.
    deduped: list[LawHeading] = []
    last_start = -1
    for h in headings:
        if h.start == last_start:
            continue
        deduped.append(h)
        last_start = h.start
    return deduped


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

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            headings = _iter_headings(text)
            sections = _build_sections(text, headings)

            stack: list[LawHeading] = []

            for section in sections:
                sec_text = text[section.start : section.end]
                if not sec_text.strip():
                    continue

                sec_heading = section.heading
                if sec_heading is not None:
                    _update_heading_stack(stack, heading=sec_heading)

                path = [h.text for h in stack]
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
                    meta["chunk_strategy"] = "laws_structured"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end

                    if sec_heading is not None:
                        meta["law_heading"] = sec_heading.text
                        meta["law_level"] = int(sec_heading.level)
                        meta["law_kind"] = sec_heading.kind
                        if sec_heading.number:
                            meta["law_number"] = sec_heading.number
                        if sec_heading.kind == "article":
                            meta["law_article"] = sec_heading.text
                    if path:
                        meta["law_path"] = path
                    if path_str:
                        meta["law_path_str"] = path_str

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
