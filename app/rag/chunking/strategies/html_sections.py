"""
HTML heading-aware chunking strategy.

Targets raw HTML documents that still contain <h1>..<h6> headings.

The chunker splits the document into heading sections first, then applies a
fallback RecursiveCharacterTextSplitter inside each section while preserving
character offsets.
"""

from __future__ import annotations

import html as _html
import logging
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class HtmlHeading:
    start: int
    end: int
    level: int
    title: str


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    heading: HtmlHeading | None


_H_TAG_RE = re.compile(r"(?is)<h(?P<level>[1-6])\b[^>]*>(?P<body>.*?)</h(?P=level)\s*>")
_TAG_STRIP_RE = re.compile(r"(?is)<[^>]+>")


def _clean_heading_text(raw_html: str) -> str:
    s = _TAG_STRIP_RE.sub("", raw_html or "")
    s = _html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _iter_headings(text: str) -> list[HtmlHeading]:
    if not text:
        return []

    headings: list[HtmlHeading] = []
    for m in _H_TAG_RE.finditer(text):
        try:
            level = int(m.group("level"))
        except Exception:
            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        title = _clean_heading_text(m.group("body") or "")
        headings.append(
            HtmlHeading(
                start=m.start(),
                end=m.end(),
                level=max(1, min(6, level)),
                title=title or f"h{level}",
            )
        )

    deduped: list[HtmlHeading] = []
    last_start = -1
    for h in headings:
        if h.start == last_start:
            continue
        deduped.append(h)
        last_start = h.start
    return deduped


def _build_sections(text: str, headings: list[HtmlHeading]) -> list[_Section]:
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


def looks_like_html_sections(text: str) -> bool:
    if not text or len(text) < 80:
        return False
    lowered = text.lower()
    if "<h" not in lowered:
        return False
    headings = _iter_headings(text)
    if len(headings) >= 2:
        return True
    if len(headings) == 1:
        return any(tag in lowered for tag in ("<html", "<body", "<div", "<p", "<section"))
    return False


class HTMLSectionsChunker(BaseChunker):
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

                path = list(heading_stack)
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
                    meta["chunk_strategy"] = "html_sections"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "html")

                    if section.heading is not None:
                        meta["html_heading"] = section.heading.title
                        meta["html_level"] = int(section.heading.level)
                    if path:
                        meta["html_path"] = path
                    if path_str:
                        meta["html_path_str"] = path_str

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

