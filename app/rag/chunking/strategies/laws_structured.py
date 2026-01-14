"""
Laws / contract structured chunking strategy.

Targets legal-style documents with explicit clause markers, e.g.:
- 第1章 / 第2节 / 第3条 / （一）...
- Article 1 / Section 2 ...

The chunker splits by detected legal headings first, then applies a fallback
RecursiveCharacterTextSplitter inside each section to respect chunk_size and
chunk_overlap while preserving character offsets.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, List, Optional

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class LawHeading:
    start: int
    end: int
    text: str
    level: int
    kind: str  # chapter|section|article|clause
    number: Optional[str] = None


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    heading: Optional[LawHeading]


_RE_CN_CHAPTER = re.compile(
    r"^\s*(?P<prefix>第[0-9一二三四五六七八九十百千]+章)\s*(?P<title>.*?)\s*$"
)
_RE_CN_SECTION = re.compile(
    r"^\s*(?P<prefix>第[0-9一二三四五六七八九十百千]+节)\s*(?P<title>.*?)\s*$"
)
_RE_CN_ARTICLE = re.compile(
    r"^\s*(?P<prefix>第[0-9一二三四五六七八九十百千]+条)\b\s*(?P<title>(?:【[^】]{1,60}】)?)\s*(?P<rest>.*)$"
)
_RE_CN_CLAUSE = re.compile(
    r"^\s*(?P<prefix>[（(][0-9一二三四五六七八九十]+[)）])\s*(?P<rest>.*)$"
)

_RE_EN_ARTICLE = re.compile(
    r"^\s*(?P<prefix>article)\s+(?P<num>\d{1,4})\b\s*[:：.\-]?\s*(?P<title>.*?)\s*$",
    flags=re.IGNORECASE,
)
_RE_EN_SECTION = re.compile(
    r"^\s*(?P<prefix>section)\s+(?P<num>\d{1,4}(?:\.\d{1,4}){0,3})\b\s*[:：.\-]?\s*(?P<title>.*?)\s*$",
    flags=re.IGNORECASE,
)


def _iter_headings(text: str) -> List[LawHeading]:
    headings: List[LawHeading] = []
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

        kind: Optional[str] = None
        level: Optional[int] = None
        num: Optional[str] = None

        if (m := _RE_CN_CHAPTER.match(raw_line)) is not None:
            kind, level = "chapter", 1
            num = (m.group("prefix") or "").strip()
        elif (m := _RE_CN_SECTION.match(raw_line)) is not None:
            kind, level = "section", 2
            num = (m.group("prefix") or "").strip()
        elif (m := _RE_CN_ARTICLE.match(raw_line)) is not None:
            kind, level = "article", 3
            num = (m.group("prefix") or "").strip()
        elif (m := _RE_CN_CLAUSE.match(raw_line)) is not None:
            kind, level = "clause", 4
            num = (m.group("prefix") or "").strip()
        elif (m := _RE_EN_ARTICLE.match(raw_line)) is not None:
            kind, level = "article", 3
            num = str(m.group("num") or "").strip()
        elif (m := _RE_EN_SECTION.match(raw_line)) is not None:
            kind, level = "section", 2
            num = str(m.group("num") or "").strip()

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
    deduped: List[LawHeading] = []
    last_start = -1
    for h in headings:
        if h.start == last_start:
            continue
        deduped.append(h)
        last_start = h.start
    return deduped


def _build_sections(text: str, headings: List[LawHeading]) -> List[_Section]:
    if not headings:
        return [_Section(start=0, end=len(text), heading=None)]

    sections: List[_Section] = []
    first = headings[0]
    if first.start > 0:
        sections.append(_Section(start=0, end=first.start, heading=None))

    for idx, h in enumerate(headings):
        start = h.start
        end = headings[idx + 1].start if idx + 1 < len(headings) else len(text)
        sections.append(_Section(start=start, end=end, heading=h))

    return sections


def _update_heading_stack(stack: List[LawHeading], *, heading: LawHeading) -> None:
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

    def split_documents(self, documents: List[Document]) -> List[Document]:
        out: List[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            headings = _iter_headings(text)
            sections = _build_sections(text, headings)

            stack: List[LawHeading] = []

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

